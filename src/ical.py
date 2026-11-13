"""Minimal iCalendar (ICS) support — no external dependencies (no dateutil).

- :func:`unfold` / :func:`parse_ics`: unfold continuation lines, parse components
  into ``{"type": ..., "props": {NAME: [(params, value), ...]},
  "components": [...]}`` — nested components (e.g. a VALARM inside a VEVENT)
  are tracked in ``components`` while the flat top-level list is preserved.
- :func:`build_vevent` / :func:`build_vtodo`: create components (UID=uuid4,
  DTSTAMP=now, ``VALUE=DATE`` for all-day).
- :func:`expand_rrule`: client-side RRULE expansion supporting
  FREQ=DAILY/WEEKLY/MONTHLY, INTERVAL, COUNT, UNTIL, BYDAY (WEEKLY) and EXDATE,
  capped at 500 occurrences.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta, timezone

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
MAX_OCCURRENCES = 500


# --- parsing -------------------------------------------------------------------


def unfold(text: str) -> list:
    """Split into logical lines; a leading space/tab continues the previous line."""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def parse_content_line(line: str):
    """``NAME;PARAM=V;...:value`` -> (NAME, {PARAM: V}, value). ':' inside quotes is safe."""
    in_quote = False
    idx = -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == ":" and not in_quote:
            idx = i
            break
    if idx < 0:
        return line.upper(), {}, ""
    head, value = line[:idx], line[idx + 1:]
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def parse_ics(text: str) -> list:
    """Parse ICS text -> list of components ``{"type", "props", "components"}``.

    A stack tracks nesting: BEGIN pushes (every component is still appended to
    the flat top-level list, preserving the historical shape; when a parent is
    open, the new component is also appended to ``stack[-1]["components"]``),
    END pops, and properties attach to the innermost open component — so a
    VALARM no longer swallows the VEVENT properties that follow it.
    """
    components = []
    stack = []
    for line in unfold(text):
        if not line.strip():
            continue
        name, params, value = parse_content_line(line)
        if name == "BEGIN":
            current = {"type": value.upper(), "props": {}, "components": []}
            components.append(current)
            if stack:
                stack[-1]["components"].append(current)
            stack.append(current)
        elif name == "END":
            if stack:
                stack.pop()
        elif stack:
            stack[-1]["props"].setdefault(name, []).append((params, value))
    return components


def prop(component: dict, name: str, default=None):
    vals = component["props"].get(name.upper())
    return vals[0][1] if vals else default


def prop_with_params(component: dict, name: str):
    vals = component["props"].get(name.upper())
    return vals[0] if vals else ({}, "")


def first_component(components: list, ctype: str) -> dict | None:
    for c in components:
        if c["type"] == ctype.upper():
            return c
    return None


# --- datetimes -------------------------------------------------------------------


def parse_dt(value: str, params: dict | None = None):
    """ICS DATE / DATE-TIME -> datetime (naive; UTC when 'Z'). VALUE=DATE -> midnight."""
    params = params or {}
    value = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or (len(value) == 8 and value.isdigit()):
        return datetime(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    v = value[:-1] if value.endswith("Z") else value
    dt = datetime.strptime(v, "%Y%m%dT%H%M%S") if "T" in v else datetime.strptime(v, "%Y%m%d")
    if value.endswith("Z"):
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_iso(s: str) -> datetime | None:
    """ISO 8601 (``2026-11-07`` or ``2026-11-07T14:30:00+01:00``) -> datetime."""
    s = (s or "").strip()
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def fmt_dt(dt, all_day: bool = False):
    """datetime -> (ics_value, is_date). UTC datetimes get the 'Z' suffix."""
    if all_day:
        d = dt.date() if isinstance(dt, datetime) else dt
        return d.strftime("%Y%m%d"), True
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt.strftime("%Y%m%dT000000"), False
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.strftime("%Y%m%dT%H%M%SZ"), False
    return dt.strftime("%Y%m%dT%H%M%S"), False


def _naive(dt):
    if isinstance(dt, datetime) and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# --- building --------------------------------------------------------------------


def esc(text) -> str:
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Fold a content line at 75 chars (continuation = leading space)."""
    out = []
    while len(line) > 75:
        out.append(line[:74])
        line = " " + line[74:]
    out.append(line)
    return "\r\n".join(out)


def _dt_line(name: str, dt, all_day: bool) -> str:
    value, is_date = fmt_dt(dt, all_day)
    return f"{name};VALUE=DATE:{value}" if is_date else f"{name}:{value}"


def unesc(text: str) -> str:
    """Inverse of :func:`esc` — undo ICS text escaping (\\, \\; \\\\ \\n)."""
    return re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1), str(text))


_DURATION_RE = re.compile(
    r"(?P<sign>-)?P(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?"
    r"(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?"
)


def parse_duration(v: str) -> timedelta:
    """Strict ISO 8601 duration -> timedelta: optional '-', then P[nW][nD][T[nH][nM][nS]]
    with at least one component. Raises ValueError otherwise."""
    s = (v or "").strip().upper()
    m = _DURATION_RE.fullmatch(s)
    if not m or not any(m.group(g) for g in ("w", "d", "h", "m", "s")):
        raise ValueError(f"invalid ISO 8601 duration: {v!r}")
    if "T" in s and not any(m.group(g) for g in ("h", "m", "s")):
        raise ValueError(f"invalid ISO 8601 duration: {v!r}")
    td = timedelta(
        weeks=int(m.group("w") or 0), days=int(m.group("d") or 0),
        hours=int(m.group("h") or 0), minutes=int(m.group("m") or 0),
        seconds=int(m.group("s") or 0),
    )
    return -td if m.group("sign") else td


def fmt_duration(td: timedelta) -> str:
    """timedelta -> canonical signed ISO 8601 duration, e.g. '-PT15M', 'P1D', 'PT0S'."""
    total = int(td.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    weeks, rem = divmod(total, 7 * 86400)
    days, rem = divmod(rem, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    date_part = f"{weeks}W" if weeks else ""
    date_part += f"{days}D" if days else ""
    time_part = f"{hours}H" if hours else ""
    time_part += f"{minutes}M" if minutes else ""
    time_part += f"{seconds}S" if seconds else ""
    if time_part:
        return f"{sign}P{date_part}T{time_part}"
    if date_part:
        return f"{sign}P{date_part}"
    return f"{sign}PT0S"


def valarm(trigger: str, description: str) -> dict:
    """VALARM component dict; ACTION:DISPLAY requires DESCRIPTION (RFC 5545)."""
    return {
        "type": "VALARM",
        "props": {
            "ACTION": [({}, "DISPLAY")],
            "DESCRIPTION": [({}, esc(description))],
            "TRIGGER": [({}, trigger)],
        },
        "components": [],
    }


def serialize_component(comp: dict) -> list:
    lines = [f"BEGIN:{comp['type']}"]
    for name, values in comp["props"].items():
        for params, value in values:
            p = "".join(f";{k}={v}" for k, v in params.items())
            lines.append(f"{name}{p}:{value}")
    for child in comp.get("components", []):
        lines.extend(serialize_component(child))
    lines.append(f"END:{comp['type']}")
    return lines


def wrap_calendar(comp_lines: list) -> str:
    body = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//nextcloud-tools//EN", *comp_lines, "END:VCALENDAR"]
    return "\r\n".join(fold(line) for line in body) + "\r\n"


def build_vevent(uid=None, summary="", start=None, end=None, all_day=False,
                 description="", location="", rrule="", reminder="", dtstamp=None) -> str:
    uid = uid or str(uuid.uuid4())
    dtstamp = dtstamp or datetime.now(timezone.utc)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{fmt_dt(dtstamp)[0]}",
        _dt_line("DTSTART", start, all_day),
        _dt_line("DTEND", end, all_day),
        f"SUMMARY:{esc(summary)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{esc(description)}")
    if location:
        lines.append(f"LOCATION:{esc(location)}")
    if rrule:
        lines.append(f"RRULE:{rrule}")
    if reminder:
        lines.extend(serialize_component(valarm(reminder, summary or "Reminder")))
    lines.append("END:VEVENT")
    return wrap_calendar(lines)


def build_vtodo(uid=None, summary="", due=None, priority=0, description="", dtstamp=None) -> str:
    uid = uid or str(uuid.uuid4())
    dtstamp = dtstamp or datetime.now(timezone.utc)
    lines = [
        "BEGIN:VTODO",
        f"UID:{uid}",
        f"DTSTAMP:{fmt_dt(dtstamp)[0]}",
        f"SUMMARY:{esc(summary)}",
        "STATUS:NEEDS-ACTION",
    ]
    if due:
        dt = parse_iso(due) if isinstance(due, str) else due
        lines.append(_dt_line("DUE", dt, len(str(due)) == 10))
    if priority:
        lines.append(f"PRIORITY:{int(priority)}")
    if description:
        lines.append(f"DESCRIPTION:{esc(description)}")
    lines.append("END:VTODO")
    return wrap_calendar(lines)


# --- RRULE expansion ---------------------------------------------------------------


def parse_rrule(rrule: str) -> dict:
    parts = {}
    for p in rrule.split(";"):
        if "=" in p:
            k, v = p.split("=", 1)
            parts[k.upper()] = v.strip()
    return parts


def _gen(freq: str, start: datetime, interval: int, byday: list):
    if freq == "DAILY":
        k = 0
        while True:
            yield start + timedelta(days=k * interval)
            k += 1
    elif freq == "WEEKLY":
        if byday:
            week0 = start - timedelta(days=start.weekday())
            w = 0
            while True:
                base = week0 + timedelta(weeks=w * interval)
                for d in sorted(byday):
                    yield base + timedelta(days=d)
                w += 1
        else:
            k = 0
            while True:
                yield start + timedelta(weeks=k * interval)
                k += 1
    elif freq == "MONTHLY":
        k = 0
        while True:
            m = start.month - 1 + k * interval
            y = start.year + m // 12
            m = m % 12 + 1
            try:
                yield start.replace(year=y, month=m)
            except ValueError:
                pass  # e.g. Feb 31 — skip that month
            k += 1
    else:
        yield start


def expand_rrule(dtstart, rrule, range_start=None, range_end=None, exdates=(), max_occ=MAX_OCCURRENCES) -> list:
    """Expand an RRULE into occurrence start datetimes, capped at ``max_occ``.

    Supports FREQ=DAILY/WEEKLY/MONTHLY, INTERVAL, COUNT, UNTIL, BYDAY (WEEKLY)
    and EXDATE. ``exdates`` is an iterable of (value, params) ICS EXDATE entries.
    """
    start = _naive(dtstart)
    r = parse_rrule(rrule) if rrule else {}
    freq = r.get("FREQ", "").upper()
    interval = max(1, int(r.get("INTERVAL") or 1))
    count = int(r["COUNT"]) if r.get("COUNT") else None
    until = None
    if r.get("UNTIL"):
        u = r["UNTIL"]
        if len(u) == 8 and u.isdigit():
            until = datetime(int(u[0:4]), int(u[4:6]), int(u[6:8]), 23, 59, 59)
        else:
            until = _naive(parse_dt(u))
    byday = []
    if freq == "WEEKLY" and r.get("BYDAY"):
        for d in r["BYDAY"].split(","):
            key = d.strip().upper()[-2:]
            if key in WEEKDAYS:
                byday.append(WEEKDAYS[key])
    exset = {_naive(parse_dt(v, p)) for v, p in exdates}
    rstart = _naive(range_start) if range_start is not None else None
    rend = _naive(range_end) if range_end is not None else None

    gen = _gen(freq, start, interval, byday) if freq in ("DAILY", "WEEKLY", "MONTHLY") else iter([start])
    out = []
    generated = 0
    for cur in gen:
        if count is not None and generated >= count:
            break
        if until is not None and cur > until:
            break
        generated += 1
        if rend is not None and cur > rend:
            break  # occurrences are non-decreasing
        if cur in exset:
            continue
        if rstart is not None and cur < rstart:
            continue
        out.append(cur)
        if len(out) >= max_occ:
            break
    return out
