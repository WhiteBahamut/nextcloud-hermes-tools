"""Calendar + tasks tools — CalDAV under ``/remote.php/dav/calendars/<user>/<cal>/``.

- ``calendar`` is the DAV directory name — shared calendars are
  ``<name>_shared_by_<Owner>``, never the display name.
- UID -> href+etag resolution uses a REPORT with a UID ``text-match``; etags
  arrive HTML-escaped in XML, so ``html.unescape`` before ``If-Match``.
- Writes always PUT with ``If-Match`` (clobber protection) and verify by
  read-back. All-day events use ``VALUE=DATE``. ``nc_cal_list`` defaults
  from = now-30d, to = now+90d; RRULEs are expanded client-side (cap 500).
"""

from __future__ import annotations

import html
import re
import uuid
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape as xml_escape

from . import client, ical, schemas
from .dav import parse_multistatus

REPORT_HEADERS = {"Content-Type": "application/xml; charset=utf-8", "Depth": "1"}


def _report(cal_href, body):
    resp = client.request("REPORT", cal_href, content=body.encode("utf-8"), headers=REPORT_HEADERS)
    return client.require(resp, (200, 207))


def _put_ics(href, body, etag=None):
    headers = {"Content-Type": "text/calendar; charset=utf-8"}
    if etag:
        headers["If-Match"] = etag
    return client.require(client.request("PUT", href, content=body.encode("utf-8"), headers=headers), (200, 201, 204))


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


def _range_bounds(args):
    now = datetime.now(timezone.utc)
    frm = ical.parse_iso(args.get("from") or "") or (now - timedelta(days=30))
    to = ical.parse_iso(args.get("to") or "") or (now + timedelta(days=90))
    if frm.tzinfo is None:
        frm = frm.replace(tzinfo=timezone.utc)
    if to.tzinfo is None:
        to = to.replace(tzinfo=timezone.utc)
    return frm.astimezone(timezone.utc), to.astimezone(timezone.utc)


def _ics(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_duration(v: str) -> timedelta:
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v or "")
    if not m:
        return timedelta(hours=1)
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi, seconds=s)


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
    raise client.NcError(404, f"no {comp} with UID {uid} in calendar {calendar}")


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
    resp = _report(cal_href, _time_range_body(_ics(rstart), _ics(rend), "VEVENT"))
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
    start = ical.parse_iso(args.get("start") or "")
    end = ical.parse_iso(args.get("end") or "")
    if start is None or end is None:
        return client.err("start and end must be ISO 8601 (YYYY-MM-DD with all_day=true, or full datetime)")
    all_day = bool(args.get("all_day"))
    uid = str(uuid.uuid4())
    body = ical.build_vevent(
        uid=uid, summary=summary, start=start, end=end, all_day=all_day,
        description=args.get("description") or "", location=args.get("location") or "",
        rrule=args.get("rrule") or "",
    )
    href = client.cal_dav(calendar) + uid + ".ics"
    _put_ics(href, body)
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got:
        return client.err(f"create verification failed: UID {uid} not in read-back", calendar=calendar, uid=uid)
    return client.ok(calendar=calendar, uid=uid, verified=True)


def _cal_edit(args):
    calendar = args["calendar"]
    uid = args["uid"]
    href, etag = _resolve_uid(calendar, uid, "VEVENT")
    vevent = ical.first_component(ical.parse_ics(client.dav_get(href).text), "VEVENT")
    if vevent is None:
        return client.err(f"no VEVENT at {href}")
    all_day = args.get("all_day") if "all_day" in args else None
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
    _put_ics(href, ical.wrap_calendar(ical.serialize_component(vevent)), etag=etag)
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got:
        return client.err(f"edit verification failed: UID {uid} not in read-back", calendar=calendar, uid=uid)
    return client.ok(calendar=calendar, uid=uid, verified=True)


def _cal_delete(args):
    calendar = args["calendar"]
    uid = args["uid"]
    href, etag = _resolve_uid(calendar, uid, "VEVENT")
    client.require(client.request("DELETE", href, headers={"If-Match": etag}), (200, 204))
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
    include_completed = bool(args.get("include_completed"))
    limit = int(args.get("limit") or 200)
    resp = _report(client.cal_dav(calendar), _comp_query_body("VTODO"))
    tasks = []
    for r in parse_multistatus(resp.text):
        ics_text = r["props"].get("calendar-data")
        if not ics_text:
            continue
        for comp in ical.parse_ics(ics_text):
            if comp["type"] != "VTODO":
                continue
            status = (ical.prop(comp, "STATUS", "") or "NEEDS-ACTION").upper()
            if status == "COMPLETED" and not include_completed:
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
            if len(tasks) >= limit:
                break
        if len(tasks) >= limit:
            break
    return client.ok(calendar=calendar, count=len(tasks), tasks=tasks)


def _task_create(args):
    calendar = args.get("calendar") or "tasks"
    summary = args.get("summary") or ""
    if not summary:
        return client.err("summary required")
    uid = str(uuid.uuid4())
    body = ical.build_vtodo(
        uid=uid, summary=summary, due=args.get("due") or "",
        priority=int(args.get("priority") or 0), description=args.get("description") or "",
    )
    href = client.cal_dav(calendar) + uid + ".ics"
    _put_ics(href, body)
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got or "STATUS:NEEDS-ACTION" not in got:
        return client.err(f"create verification failed for UID {uid}", calendar=calendar, uid=uid)
    return client.ok(calendar=calendar, uid=uid, verified=True)


def _task_complete(args):
    calendar = args.get("calendar") or "tasks"
    uid = args["uid"]
    href, etag = _resolve_uid(calendar, uid, "VTODO")
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


TOOLS = [
    ("nc_cal_list", schemas.NC_CAL_LIST, client.tool(_cal_list)),
    ("nc_cal_create", schemas.NC_CAL_CREATE, client.tool(_cal_create)),
    ("nc_cal_edit", schemas.NC_CAL_EDIT, client.tool(_cal_edit)),
    ("nc_cal_delete", schemas.NC_CAL_DELETE, client.tool(_cal_delete)),
    ("nc_task_list", schemas.NC_TASK_LIST, client.tool(_task_list)),
    ("nc_task_create", schemas.NC_TASK_CREATE, client.tool(_task_create)),
    ("nc_task_complete", schemas.NC_TASK_COMPLETE, client.tool(_task_complete)),
]
