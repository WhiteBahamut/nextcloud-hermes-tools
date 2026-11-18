"""Calendar + tasks tools — CalDAV under ``/remote.php/dav/calendars/<user>/<cal>/``.

- ``calendar`` is the DAV directory name — shared calendars are
  ``<name>_shared_by_<Owner>``, never the display name.
- UID -> href+etag resolution uses a REPORT with a UID ``text-match``; etags
  arrive HTML-escaped in XML, so ``html.unescape`` before ``If-Match``.
- Writes always PUT with ``If-Match`` (clobber protection) and verify by
  read-back. All-day events use ``VALUE=DATE``. ``nc_cal_list`` defaults
  from = now-30d, to = now+90d; RRULEs are expanded client-side (cap 500).
- A 404 from a missing calendar collection is self-healing: the error lists
  the available collections (PROPFIND Depth 1 on the calendar home).
- ``nc_cal_list_calendars`` lists the calendar home itself: PROPFIND Depth 1 on
  ``/remote.php/dav/calendars/<user>/`` requesting ``resourcetype`` + ``displayname``.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import unquote
from xml.sax.saxutils import escape as xml_escape

from . import client, dav, ical, schemas
from .dav import parse_multistatus

REPORT_HEADERS = {"Content-Type": "application/xml; charset=utf-8", "Depth": "1"}


def _report(cal_href, body):
    resp = client.request("REPORT", cal_href, content=body.encode("utf-8"), headers=REPORT_HEADERS)
    return client.require(resp, (200, 207))


def _put_ics(href, body, etag=None):
    return client.dav_put(href, body.encode("utf-8"), "text/calendar; charset=utf-8", etag=etag)


def _time_range_body(rstart_ics, rend_ics, comp="VEVENT"):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<cal:calendar-query xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">'
        "<d:prop><d:getetag/><cal:calendar-data/></d:prop>"
        '<cal:filter><cal:comp-filter name="VCALENDAR">'
        f'<cal:comp-filter name="{comp}">'
        f'<cal:time-range start="{rstart_ics}" end="{rend_ics}"/>'
        f"</cal:comp-filter></cal:comp-filter></cal:filter>"
        "</cal:calendar-query>"
    )


def _uid_query_body(uid, comp="VEVENT"):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<cal:calendar-query xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">'
        "<d:prop><d:getetag/><cal:calendar-data/></d:prop>"
        '<cal:filter><cal:comp-filter name="VCALENDAR">'
        f'<cal:comp-filter name="{comp}">'
        '<cal:prop-filter name="UID">'
        f'<cal:text-match collation="i;octet">{xml_escape(uid)}</cal:text-match>'
        "</cal:prop-filter>"
        f"</cal:comp-filter></cal:comp-filter></cal:filter>"
        "</cal:calendar-query>"
    )


def _comp_query_body(comp="VTODO"):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<cal:calendar-query xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">'
        "<d:prop><d:getetag/><cal:calendar-data/></d:prop>"
        '<cal:filter><cal:comp-filter name="VCALENDAR">'
        f'<cal:comp-filter name="{comp}"/>'
        "</cal:comp-filter></cal:filter></cal:calendar-query>"
    )


_DETECTED_TZ = None  # process-wide cache of the auto-detected server timezone


def _detect_server_tz():
    """Auto-detect the server timezone: PROPFIND Depth:0 on the calendar home
    (``client.cal_home()`` -> /remote.php/dav/calendars/<user>/) requesting
    {urn:ietf:params:xml:ns:caldav}calendar-timezone, then ZoneInfo(TZID).
    Any absence/error/invalid TZID -> UTC. Never raises."""
    try:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">'
            "<d:prop><cal:calendar-timezone/></d:prop></d:propfind>"
        )
        resp = client.request("PROPFIND", client.cal_home(), content=body,
                              headers={"Depth": "0", "Content-Type": "application/xml; charset=utf-8"})
        if resp.status_code in (200, 207):
            for r in parse_multistatus(resp.text):
                v = r["props"].get("calendar-timezone")
                if v:
                    m = re.search(r"TZID:([^\r\n]+)", v)
                    if m:
                        return ZoneInfo(m.group(1).strip())
            # RFC 4791 §5.2.2 serializes calendar-timezone as a nested VTIMEZONE
            # component; parse_multistatus keeps only direct text, so scan the raw
            # XML too (nested <TZID> element, or flat "TZID:..." itertext).
            try:
                for el in ET.fromstring(resp.text).iter():
                    if el.tag.rsplit("}", 1)[-1] != "calendar-timezone":
                        continue
                    for sub in el.iter():
                        if sub.tag.rsplit("}", 1)[-1].lower() == "tzid" and sub.text and sub.text.strip():
                            return ZoneInfo(sub.text.strip())
                    m = re.search(r"TZID:([^\r\n]+)", "".join(el.itertext()))
                    if m:
                        return ZoneInfo(m.group(1).strip())
            except Exception:
                pass
    except Exception:
        pass
    return timezone.utc


def _server_tz():
    """Effective zone for tool-generated default times: non-empty server_timezone
    wins (invalid name -> UTC); empty -> auto-detected server timezone (cached)."""
    name = str(client.get_config("server_timezone", "") or "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            return timezone.utc
    global _DETECTED_TZ
    if _DETECTED_TZ is None:
        _DETECTED_TZ = _detect_server_tz()
    return _DETECTED_TZ


def _range_bounds(args):
    frm = ical.parse_iso(args.get("from") or "")
    to = ical.parse_iso(args.get("to") or "")
    if frm is None or to is None:
        now = datetime.now(_server_tz())  # detection fires only when a bound is missing
        if frm is None:
            frm = now - timedelta(days=30)
        if to is None:
            to = now + timedelta(days=90)
    return frm, to


def _ics(dt) -> str:
    return ical.fmt_dt(dt)[0]


def _parse_duration(v: str) -> timedelta:
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v or "")
    if not m:
        return timedelta(hours=1)
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi, seconds=s)


def _reminder_trigger(v) -> str | None:
    """reminder arg -> canonical VALARM TRIGGER (e.g. '-PT15M'), or None for 0/''/None
    (no reminder / remove). Raises ValueError on anything else."""
    if v is None or v == "" or v == 0:
        return None
    if not isinstance(v, str):
        raise ValueError(f"reminder must be an ISO 8601 duration string, got {type(v).__name__}")
    return ical.fmt_duration(ical.parse_duration(v.strip().upper()))


def _check_dt_args(start_raw, end_raw, all_day, vevent=None):
    """Pre-write validation of start/end raw strings for create/edit.

    vevent: existing VEVENT in edit mode (the unchanged counterpart's style
    joins the consistency check); None in create mode. Returns an error
    message, or None when valid. Never raises.
    """
    for name, raw in (("start", start_raw), ("end", end_raw)):
        if raw and ical.is_date_only(raw) and not all_day:
            return f"date-only {name} (YYYY-MM-DD) requires all_day=true"
    if all_day:
        return None
    styles = set()
    for raw in (start_raw, end_raw):
        if raw and not ical.is_date_only(raw):
            dt = ical.parse_iso(raw)
            if dt is not None:
                styles.add(ical.dt_style(dt))
    if vevent is not None:
        for raw, other in ((start_raw, "DTEND"), (end_raw, "DTSTART")):
            if raw and not ical.is_date_only(raw):
                p, v = ical.prop_with_params(vevent, other)
                if v:
                    styles.add(ical.dt_style(ical.parse_dt(v, p)))
    if len(styles) > 1:
        return ("start and end must use one offset style "
                "(all Z, all ±HH:MM, or all floating); got mixed styles")
    return None


def _event_dict(vevent, rstart, rend) -> dict:
    uid = ical.prop(vevent, "UID", "")
    dtstart_params, dtstart_val = ical.prop_with_params(vevent, "DTSTART")
    all_day = dtstart_params.get("VALUE", "").upper() == "DATE"
    start = ical.parse_dt(dtstart_val, dtstart_params)
    dtend_params, dtend_val = ical.prop_with_params(vevent, "DTEND")
    if dtend_val:
        end = ical.parse_dt(dtend_val, dtend_params)
    else:
        _, dur_val = ical.prop_with_params(vevent, "DURATION")
        end = start + _parse_duration(dur_val) if dur_val else start + timedelta(hours=1)
    rrule = ical.prop(vevent, "RRULE", "")
    exdates = vevent["props"].get("EXDATE", [])
    duration = end - start
    occs = ical.expand_rrule(start, rrule, rstart, rend, exdates=exdates)
    return {
        "uid": uid,
        "summary": ical.prop(vevent, "SUMMARY", ""),
        "description": ical.prop(vevent, "DESCRIPTION", ""),
        "location": ical.prop(vevent, "LOCATION", ""),
        "all_day": all_day,
        "rrule": rrule,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "occurrences": [{"start": o.isoformat(), "end": (o + duration).isoformat()} for o in occs],
    }


class UidNotFound(client.NcError):
    """No component with that UID (status 404) — distinct from a missing calendar collection."""


def _resolve_uid(calendar, uid, comp="VEVENT"):
    """UID -> (href, etag); etag unescaped (etags arrive HTML-escaped in XML)."""
    cal_href = client.cal_dav(calendar)
    resp = _report(cal_href, _uid_query_body(uid, comp))
    for r in parse_multistatus(resp.text):
        href = r["href"]
        if href.rstrip("/").endswith("/"):
            continue
        etag = html.unescape(r["props"].get("getetag") or "")
        return href, etag
    raise UidNotFound(404, f"no {comp} with UID {uid} in calendar {calendar}")


def _calendar_names() -> list[str]:
    """DAV directory names of the user's calendar collections (for 404 error messages)."""
    return [c["name"] for c in dav.list_collections(client.cal_home())]


def _missing_calendar_err(calendar):
    """404 on a missing calendar collection -> err JSON listing the available calendars."""
    try:
        available = _calendar_names()
    except Exception:
        available = []
    msg = f"calendar '{calendar}' not found"
    if available:
        msg += f"; available calendars: {', '.join(available)}"
    return client.err(msg, calendar=calendar, available=available)


def _cal_list_calendars(args):
    """PROPFIND Depth 1 on the calendar home -> DAV dir name + display name per calendar collection."""
    cals = dav.list_collections(client.cal_home())
    return client.ok(count=len(cals), calendars=cals)


def _set_dt(comp, name, dt, all_day):
    if all_day is None:
        p, _ = ical.prop_with_params(comp, name)
        all_day = p.get("VALUE", "").upper() == "DATE"
    val, is_date = ical.fmt_dt(dt, bool(all_day))
    comp["props"][name] = [({"VALUE": "DATE"} if is_date else {}, val)]


# --- calendar events -------------------------------------------------------------


def _cal_list(args):
    calendar = args.get("calendar") or "personal"
    limit = int(args.get("limit") or 100)
    rstart, rend = _range_bounds(args)
    cal_href = client.cal_dav(calendar)
    try:
        resp = _report(cal_href, _time_range_body(_ics(rstart), _ics(rend), "VEVENT"))
    except client.NcError as exc:
        if exc.status == 404:
            return _missing_calendar_err(calendar)
        raise
    events = []
    for r in parse_multistatus(resp.text):
        ics_text = r["props"].get("calendar-data")
        if not ics_text:
            continue
        for comp in ical.parse_ics(ics_text):
            if comp["type"] != "VEVENT":
                continue
            events.append(_event_dict(comp, rstart, rend))
            if len(events) >= limit:
                break
        if len(events) >= limit:
            break
    return client.ok(**{"calendar": calendar, "from": rstart.isoformat(), "to": rend.isoformat(), "count": len(events), "events": events})


def _cal_create(args):
    calendar = args.get("calendar") or "personal"
    summary = args.get("summary") or ""
    all_day = bool(args.get("all_day"))
    start = ical.parse_iso(args.get("start") or "")
    end = ical.parse_iso(args.get("end") or "")
    if start is None or end is None:
        return client.err("start and end must be ISO 8601 (YYYY-MM-DD with all_day=true, or full datetime)")
    if msg := _check_dt_args(args.get("start") or "", args.get("end") or "", all_day):
        return client.err(msg)
    uid = str(uuid.uuid4())
    try:
        trigger = _reminder_trigger(args.get("reminder"))
    except ValueError as e:
        return client.err(f"invalid reminder: {e}")
    body = ical.build_vevent(
        uid=uid, summary=summary, start=start, end=end, all_day=all_day,
        description=args.get("description") or "", location=args.get("location") or "",
        rrule=args.get("rrule") or "", reminder=trigger or "",
    )
    href = client.cal_dav(calendar) + uid + ".ics"
    try:
        _put_ics(href, body)
    except client.NcError as exc:
        if exc.status == 404:
            return _missing_calendar_err(calendar)
        raise
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got:
        return client.err(f"create verification failed: UID {uid} not in read-back", calendar=calendar, uid=uid)
    if trigger and trigger not in got:
        return client.err(f"create verification failed: TRIGGER {trigger} not in read-back", calendar=calendar, uid=uid)
    return client.ok(calendar=calendar, uid=uid, verified=True)


def _cal_edit(args):
    calendar = args["calendar"]
    uid = args["uid"]
    href, etag = _resolve_uid(calendar, uid, "VEVENT")
    vevent = ical.first_component(ical.parse_ics(client.dav_get(href).text), "VEVENT")
    if vevent is None:
        return client.err(f"no VEVENT at {href}")
    all_day = args.get("all_day") if "all_day" in args else None
    if all_day is None:
        _p, _ = ical.prop_with_params(vevent, "DTSTART")
        all_day = _p.get("VALUE", "").upper() == "DATE"
    if msg := _check_dt_args(args.get("start") or "", args.get("end") or "", all_day, vevent=vevent):
        return client.err(msg)
    if args.get("summary"):
        vevent["props"]["SUMMARY"] = [({}, ical.esc(args["summary"]))]
    if args.get("start"):
        _set_dt(vevent, "DTSTART", ical.parse_iso(args["start"]), all_day)
    if args.get("end"):
        _set_dt(vevent, "DTEND", ical.parse_iso(args["end"]), all_day)
    if all_day is not None:
        for name in ("DTSTART", "DTEND"):
            if name in vevent["props"]:
                p, v = vevent["props"][name][0]
                _set_dt(vevent, name, ical.parse_dt(v, p), bool(all_day))
    if "description" in args:
        vevent["props"]["DESCRIPTION"] = [({}, ical.esc(args.get("description") or ""))]
    if "location" in args:
        vevent["props"]["LOCATION"] = [({}, ical.esc(args.get("location") or ""))]
    if "rrule" in args:
        if args.get("rrule"):
            vevent["props"]["RRULE"] = [({}, args["rrule"])]
        else:
            vevent["props"].pop("RRULE", None)
    if "reminder" in args:
        try:
            trigger = _reminder_trigger(args["reminder"])
        except ValueError as e:
            return client.err(f"invalid reminder: {e}")
        children = vevent.setdefault("components", [])
        children[:] = [c for c in children if c["type"] != "VALARM"]
        if trigger:
            summary = ical.unesc(ical.prop(vevent, "SUMMARY", "") or "")
            children.append(ical.valarm(trigger, summary or "Reminder"))
    _put_ics(href, ical.wrap_calendar(ical.serialize_component(vevent)), etag=etag)
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got:
        return client.err(f"edit verification failed: UID {uid} not in read-back", calendar=calendar, uid=uid)
    if "reminder" in args:
        if trigger and trigger not in got:
            return client.err(f"edit verification failed: TRIGGER {trigger} not in read-back", calendar=calendar, uid=uid)
        if not trigger and "BEGIN:VALARM" in got:
            return client.err("edit verification failed: VALARM still present in read-back", calendar=calendar, uid=uid)
    return client.ok(calendar=calendar, uid=uid, verified=True)


def _cal_delete(args):
    calendar = args["calendar"]
    uid = args["uid"]
    href, etag = _resolve_uid(calendar, uid, "VEVENT")
    client.require(client.dav_delete(href, headers={"If-Match": etag}), (200, 204))
    try:
        client.dav_get(href)
    except client.NcError as exc:
        if exc.status == 404:
            return client.ok(calendar=calendar, uid=uid, deleted=True, verified=True)
        raise
    return client.err(f"delete verification failed: {href} still readable", calendar=calendar, uid=uid)


# --- tasks (VTODO) -----------------------------------------------------------------


def _task_list(args):
    calendar = args.get("calendar") or "tasks"
    include_completed = args.get("include_completed")
    if include_completed is None:
        include_completed = True
    limit = int(args.get("limit") or 200)
    try:
        resp = _report(client.cal_dav(calendar), _comp_query_body("VTODO"))
    except client.NcError as exc:
        if exc.status == 404:
            return _missing_calendar_err(calendar)
        raise
    tasks = []
    total = n_open = n_closed = 0
    for r in parse_multistatus(resp.text):
        ics_text = r["props"].get("calendar-data")
        if not ics_text:
            continue
        for comp in ical.parse_ics(ics_text):
            if comp["type"] != "VTODO":
                continue
            status = (ical.prop(comp, "STATUS", "") or "NEEDS-ACTION").upper()
            total += 1
            if status == "COMPLETED":
                n_closed += 1
            else:
                n_open += 1
            if status == "COMPLETED" and not include_completed:
                continue
            if len(tasks) >= limit:
                continue
            tasks.append({
                "uid": ical.prop(comp, "UID", ""),
                "summary": ical.prop(comp, "SUMMARY", ""),
                "status": status,
                "due": ical.prop(comp, "DUE", ""),
                "priority": ical.prop(comp, "PRIORITY", ""),
                "percent": ical.prop(comp, "PERCENT-COMPLETE", ""),
                "description": ical.prop(comp, "DESCRIPTION", ""),
            })
    return client.ok(calendar=calendar, count=len(tasks), tasks=tasks,
                     stats={"total": total, "open": n_open, "closed": n_closed})


def _task_create(args):
    calendar = args.get("calendar") or "tasks"
    summary = args.get("summary") or ""
    if not summary:
        return client.err("summary required")
    status = (args.get("status") or "NEEDS-ACTION").upper()
    if status not in ("NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED"):
        return client.err(f"invalid status {status!r}: expected one of NEEDS-ACTION, IN-PROCESS, COMPLETED, CANCELLED")
    uid = str(uuid.uuid4())
    body = ical.build_vtodo(
        uid=uid, summary=summary, due=args.get("due") or "",
        priority=int(args.get("priority") or 0), description=args.get("description") or "",
        status=status,
    )
    href = client.cal_dav(calendar) + uid + ".ics"
    try:
        _put_ics(href, body)
    except client.NcError as exc:
        if exc.status == 404:
            return _missing_calendar_err(calendar)
        raise
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got or f"STATUS:{status}" not in got:
        return client.err(f"create verification failed for UID {uid}", calendar=calendar, uid=uid)
    return client.ok(calendar=calendar, uid=uid, status=status, verified=True)


def _task_complete(args):
    calendar = args.get("calendar") or "tasks"
    uid = args["uid"]
    try:
        href, etag = _resolve_uid(calendar, uid, "VTODO")
    except UidNotFound:
        raise
    except client.NcError as exc:
        if exc.status == 404:
            return _missing_calendar_err(calendar)
        raise
    vtodo = ical.first_component(ical.parse_ics(client.dav_get(href).text), "VTODO")
    if vtodo is None:
        return client.err(f"no VTODO at {href}")
    vtodo["props"]["STATUS"] = [({}, "COMPLETED")]
    vtodo["props"]["COMPLETED"] = [({}, ical.fmt_dt(datetime.now(timezone.utc))[0])]
    vtodo["props"]["PERCENT-COMPLETE"] = [({}, "100")]
    _put_ics(href, ical.wrap_calendar(ical.serialize_component(vtodo)), etag=etag)
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got or "STATUS:COMPLETED" not in got:
        return client.err(f"complete verification failed for UID {uid}", calendar=calendar, uid=uid)
    return client.ok(calendar=calendar, uid=uid, status="COMPLETED", verified=True)


def _task_reopen(args):
    calendar = args.get("calendar") or "tasks"
    uid = args["uid"]
    try:
        href, etag = _resolve_uid(calendar, uid, "VTODO")
    except UidNotFound:
        raise
    except client.NcError as exc:
        if exc.status == 404:
            return _missing_calendar_err(calendar)
        raise
    vtodo = ical.first_component(ical.parse_ics(client.dav_get(href).text), "VTODO")
    if vtodo is None:
        return client.err(f"no VTODO at {href}")
    vtodo["props"]["STATUS"] = [({}, "NEEDS-ACTION")]
    vtodo["props"].pop("COMPLETED", None)
    vtodo["props"]["PERCENT-COMPLETE"] = [({}, "0")]
    _put_ics(href, ical.wrap_calendar(ical.serialize_component(vtodo)), etag=etag)
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got or "STATUS:NEEDS-ACTION" not in got or "COMPLETED:" in got:
        return client.err(f"reopen verification failed for UID {uid}", calendar=calendar, uid=uid)
    return client.ok(calendar=calendar, uid=uid, status="NEEDS-ACTION", verified=True)


TOOLS = [
    ("nc_cal_list", schemas.NC_CAL_LIST, client.tool(_cal_list)),
    ("nc_cal_list_calendars", schemas.NC_CAL_LIST_CALENDARS, client.tool(_cal_list_calendars)),
    ("nc_cal_create", schemas.NC_CAL_CREATE, client.tool(_cal_create)),
    ("nc_cal_edit", schemas.NC_CAL_EDIT, client.tool(_cal_edit)),
    ("nc_cal_delete", schemas.NC_CAL_DELETE, client.tool(_cal_delete)),
    ("nc_task_list", schemas.NC_TASK_LIST, client.tool(_task_list)),
    ("nc_task_create", schemas.NC_TASK_CREATE, client.tool(_task_create)),
    ("nc_task_complete", schemas.NC_TASK_COMPLETE, client.tool(_task_complete)),
    ("nc_task_reopen", schemas.NC_TASK_REOPEN, client.tool(_task_reopen)),
]
