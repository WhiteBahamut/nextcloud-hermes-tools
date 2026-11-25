"""Calendar handlers: VALARM handling, read-back verification, time defaults."""

from datetime import datetime
import re

import httpx
import pytest
from conftest import CAL_DAV, MockNc, make_caller, multistatus
from nextcloud_tools import client, tools_cal


# --- calendar handlers ---------------------------------------------------------------


def test_cal_list_time_range_report_and_rrule_expansion(nc, call):
    ev = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:e1\r\nDTSTAMP:20261101T000000Z\r\n"
        "DTSTART:20261110T140000Z\r\nDTEND:20261110T150000Z\r\nSUMMARY:Meeting\r\nRRULE:FREQ=DAILY;COUNT=3\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )

    def h(req):
        assert req.method == "REPORT"
        body = req.content.decode()
        assert "time-range" in body and 'start="20261101T000000Z"' in body and 'end="20261130T235959Z"' in body
        return multistatus([(f"{CAL_DAV}/e1.ics", f"<cal:calendar-data>{ev}</cal:calendar-data>")])

    nc.handler = h
    res = call("nc_cal_list", {"calendar": "personal", "from": "2026-11-01T00:00:00Z", "to": "2026-11-30T23:59:59Z"})
    assert res["ok"]
    event = res["events"][0]
    assert event["summary"] == "Meeting" and event["uid"] == "e1"
    assert len(event["occurrences"]) == 3
    assert event["occurrences"][0]["end"].startswith("2026-11-10T15:00:00")


def test_cal_list_calendars_home_propfind(nc, call):
    home = "/remote.php/dav/calendars/bot"

    def h(req):
        assert req.method == "PROPFIND" and req.url.path == home + "/"
        assert req.headers["Depth"] == "1"
        return multistatus([
            (f"{home}/", '<d:resourcetype><d:collection/></d:resourcetype><d:displayname>Calendars</d:displayname>'),
            (f"{home}/personal", '<d:resourcetype><d:collection/></d:resourcetype><d:displayname>Personal</d:displayname>'),
            (f"{home}/work", '<d:resourcetype><d:collection/></d:resourcetype><d:displayname>Work</d:displayname>'),
            (f"{home}/stray.ics", '<d:resourcetype/>'),  # non-collection: excluded
        ])

    nc.handler = h
    res = call("nc_cal_list_calendars", {})
    assert res["ok"] and res["count"] == 2
    assert [r.method for r in nc.requests] == ["PROPFIND"]
    assert res["calendars"] == [{"name": "personal", "display_name": "Personal"},
                                {"name": "work", "display_name": "Work"}]  # home excluded, sorted


def test_cal_create_all_day_value_date_and_readback(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "PUT":
            state[p] = req.content.decode()
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, text=state[p]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_cal_create", {
        "calendar": "personal", "summary": "Xmas", "start": "2026-12-24",
        "end": "2026-12-25", "all_day": True, "rrule": "FREQ=YEARLY;COUNT=2",
    })
    assert res["ok"] and res["verified"]
    body = state[f"{CAL_DAV}/{res['uid']}.ics"]
    assert "DTSTART;VALUE=DATE:20261224" in body
    assert "DTEND;VALUE=DATE:20261225" in body
    assert f"UID:{res['uid']}" in body and "RRULE:FREQ=YEARLY;COUNT=2" in body


ALARM_ICS = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:uid-rem\r\nDTSTAMP:20261101T000000Z\r\n"
    "DTSTART:20261110T140000\r\nDTEND:20261110T150000\r\nSUMMARY:Standup\\, daily\r\n"
    "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:old\r\nTRIGGER:-PT5M\r\nEND:VALARM\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n"
)


def _edit_handler(nc, state, ics, uid):
    def h(req):
        p = req.url.path
        if req.method == "REPORT":
            return multistatus([(f"{CAL_DAV}/{uid}.ics",
                                 f'<d:getetag>&amp;quot;e1&amp;quot;</d:getetag><cal:calendar-data>{ics}</cal:calendar-data>')])
        if req.method == "GET":
            return httpx.Response(200, text=state.get(p, ics))
        if req.method == "PUT":
            state[p] = req.content.decode()
            return httpx.Response(204)
        return httpx.Response(404, text="nf")
    nc.handler = h


def test_cal_create_with_reminder_valarm(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "PUT":
            state[p] = req.content.decode()
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, text=state[p]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_cal_create", {
        "calendar": "personal", "summary": "Dentist", "start": "2026-11-10T14:00:00Z",
        "end": "2026-11-10T15:00:00Z", "reminder": "-PT15M",
    })
    assert res["ok"] and res["verified"]
    body = state[f"{CAL_DAV}/{res['uid']}.ics"]
    assert "BEGIN:VALARM" in body
    assert "TRIGGER:-PT15M" in body
    assert "ACTION:DISPLAY" in body
    assert "DESCRIPTION:Dentist" in body


def test_cal_create_without_reminder_has_no_valarm(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "PUT":
            state[p] = req.content.decode()
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, text=state[p]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_cal_create", {
        "calendar": "personal", "summary": "Plain", "start": "2026-11-10T14:00:00Z",
        "end": "2026-11-10T15:00:00Z",
    })
    assert res["ok"] and res["verified"]
    assert "VALARM" not in state[f"{CAL_DAV}/{res['uid']}.ics"]


def test_cal_create_invalid_reminder_writes_nothing(nc, call):
    nc.handler = lambda req: httpx.Response(404, text="nf")
    res = call("nc_cal_create", {
        "calendar": "personal", "summary": "X", "start": "2026-11-10T14:00:00Z",
        "end": "2026-11-10T15:00:00Z", "reminder": "banana",
    })
    assert res["ok"] is False
    assert "invalid reminder" in res["error"]
    assert nc.find("PUT", "") == []


def test_cal_edit_replaces_reminder_valarm(nc, call):
    uid = "uid-rem"
    state = {}
    _edit_handler(nc, state, ALARM_ICS, uid)
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "reminder": "-PT30M"})
    assert res["ok"] and res["verified"]
    body = state[f"{CAL_DAV}/{uid}.ics"]
    assert "TRIGGER:-PT30M" in body
    assert "TRIGGER:-PT5M" not in body
    assert body.count("BEGIN:VALARM") == 1
    assert "DESCRIPTION:Standup\\, daily" in body  # SUMMARY reused without double-escaping


def test_cal_edit_reminder_zero_removes_valarm(nc, call):
    uid = "uid-rem"
    state = {}
    _edit_handler(nc, state, ALARM_ICS, uid)
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "reminder": 0})
    assert res["ok"] and res["verified"]
    assert "BEGIN:VALARM" not in state[f"{CAL_DAV}/{uid}.ics"]


def test_cal_edit_reminder_empty_string_removes_valarm(nc, call):
    # B4 tripwire: the host never injects schema defaults — an explicitly sent
    # reminder="" must clear the VALARM (like 0), not act as an omitted key
    uid = "uid-rem"
    state = {}
    _edit_handler(nc, state, ALARM_ICS, uid)
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "reminder": ""})
    assert res["ok"] and res["verified"]
    body = state[f"{CAL_DAV}/{uid}.ics"]
    assert "BEGIN:VALARM" not in body  # PUT body and read-back (same body) have no VALARM


def test_cal_edit_preserves_valarm_on_other_edits(nc, call):
    uid = "uid-rem"
    state = {}
    _edit_handler(nc, state, ALARM_ICS, uid)
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "summary": "new"})
    assert res["ok"] and res["verified"]
    body = state[f"{CAL_DAV}/{uid}.ics"]
    assert "BEGIN:VALARM" in body and "TRIGGER:-PT5M" in body


def test_cal_edit_all_day_converts_dt_to_value_date(nc, call):
    uid = "uid-ad"
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:uid-ad\r\nDTSTAMP:20261101T000000Z\r\n"
        "DTSTART:20261110T140000\r\nDTEND:20261110T150000\r\nSUMMARY:timed\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    state = {}
    _edit_handler(nc, state, ics, uid)
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "all_day": True})
    assert res["ok"] and res["verified"]
    body = state[f"{CAL_DAV}/{uid}.ics"]
    assert "DTSTART;VALUE=DATE:20261110" in body
    assert "DTEND;VALUE=DATE:20261110" in body


def test_cal_create_reminder_readback_mismatch_fails(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "PUT":
            state[p] = req.content.decode()
            return httpx.Response(201)
        if req.method == "GET":
            if p not in state:
                return httpx.Response(404, text="nf")
            return httpx.Response(200, text=state[p].replace("TRIGGER:-PT15M", "TRIGGER:-PT1M"))
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_cal_create", {
        "calendar": "personal", "summary": "Dentist", "start": "2026-11-10T14:00:00Z",
        "end": "2026-11-10T15:00:00Z", "reminder": "-PT15M",
    })
    assert res["ok"] is False
    assert "TRIGGER -PT15M" in res["error"]


def test_cal_edit_reminder_set_readback_mismatch_fails(nc, call):
    uid = "uid-rem"

    def h(req):
        p = req.url.path
        if req.method == "REPORT":
            return multistatus([(f"{CAL_DAV}/{uid}.ics",
                                 f'<d:getetag>&amp;quot;e1&amp;quot;</d:getetag><cal:calendar-data>{ALARM_ICS}</cal:calendar-data>')])
        if req.method == "GET":
            return httpx.Response(200, text=ALARM_ICS)  # read-back still shows the old TRIGGER
        if req.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "reminder": "-PT30M"})
    assert res["ok"] is False
    assert "TRIGGER -PT30M" in res["error"]


def test_cal_edit_reminder_removal_readback_mismatch_fails(nc, call):
    uid = "uid-rem"

    def h(req):
        p = req.url.path
        if req.method == "REPORT":
            return multistatus([(f"{CAL_DAV}/{uid}.ics",
                                 f'<d:getetag>&amp;quot;e1&amp;quot;</d:getetag><cal:calendar-data>{ALARM_ICS}</cal:calendar-data>')])
        if req.method == "GET":
            return httpx.Response(200, text=ALARM_ICS)  # read-back still contains the VALARM
        if req.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "reminder": 0})
    assert res["ok"] is False
    assert "VALARM still present" in res["error"]


def test_cal_edit_unescapes_etag_into_if_match(nc, call):
    uid = "uid-1"
    # etag arrives HTML-escaped inside the XML (&amp;quot; -> text &quot; -> unescape ")
    etag_xml = "&amp;quot;W/&amp;quot;abc&amp;quot;&amp;quot;"
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:uid-1\r\nDTSTAMP:20261101T000000Z\r\n"
        "DTSTART:20261110T140000\r\nDTEND:20261110T150000\r\nSUMMARY:old\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "REPORT":
            return multistatus([(f"{CAL_DAV}/{uid}.ics",
                                 f"<d:getetag>{etag_xml}</d:getetag><cal:calendar-data>{ics}</cal:calendar-data>")])
        if req.method == "GET":
            return httpx.Response(200, text=state.get(p, ics))
        if req.method == "PUT":
            state[p] = req.content.decode()
            return httpx.Response(204)
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "summary": "new"})
    assert res["ok"] and res["verified"]
    put = nc.find("PUT", "")[0]
    assert put.headers["If-Match"] == '"W/"abc""'  # html.unescape applied
    assert "SUMMARY:new" in state[f"{CAL_DAV}/{uid}.ics"]
    assert "UID:uid-1" in state[f"{CAL_DAV}/{uid}.ics"]


def test_cal_delete_if_match_and_404_verify(nc, call):
    uid = "uid-9"
    state = {f"{CAL_DAV}/{uid}.ics": "x"}

    def h(req):
        p = req.url.path
        if req.method == "REPORT":
            return multistatus([(f"{CAL_DAV}/{uid}.ics", '<d:getetag>&amp;quot;e9&amp;quot;</d:getetag>')])
        if req.method == "DELETE":
            assert req.headers["If-Match"] == '"e9"'
            state.pop(p, None)
            return httpx.Response(204)
        if req.method == "GET":
            return httpx.Response(200, text="x") if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_cal_delete", {"calendar": "personal", "uid": uid})
    assert res["ok"] and res["deleted"] and res["verified"]


# --- pass-through times + server_timezone defaults ----------------------------------


def _nc_with_settings(monkeypatch, settings):
    monkeypatch.setenv("TALK_SERVER_URL", "https://nc.example")
    monkeypatch.setenv("TALK_USER", "bot")
    monkeypatch.setenv("TALK_APP_PASSWORD", "s3cret-pw")
    monkeypatch.setattr(tools_cal, "_DETECTED_TZ", None)  # reset detection cache per test
    _ctx, call = make_caller(settings)
    mock = MockNc()
    http = httpx.Client(base_url="https://nc.example", transport=httpx.MockTransport(mock),
                        headers={"OCS-APIRequest": "true", "Accept": "application/json"})
    monkeypatch.setattr(client, "get_client", lambda: http)
    return mock, call


def _put_get_state_handler(state):
    def h(req):
        p = req.url.path
        if req.method == "PUT":
            state[p] = req.content.decode()
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, text=state[p]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")
    return h


def test_cal_create_passes_times_through(nc, call):
    state = {}
    nc.handler = _put_get_state_handler(state)
    cases = [
        ("2026-11-10T14:00:00Z", "2026-11-10T15:00:00Z", "DTSTART:20261110T140000Z"),
        ("2026-11-10T14:00:00+02:00", "2026-11-10T15:00:00+02:00", "DTSTART:20261110T140000"),
        ("2026-11-10T14:00:00", "2026-11-10T15:00:00", "DTSTART:20261110T140000"),
    ]
    for start, end, expected in cases:
        res = call("nc_cal_create", {"calendar": "personal", "summary": "T", "start": start, "end": end})
        assert res["ok"] and res["verified"], res
        body = state[f"{CAL_DAV}/{res['uid']}.ics"]
        assert expected in body, (start, body)
    # the +02:00 wall time must NOT have been converted to UTC
    bodies = list(state.values())
    assert not any("DTSTART:20261110T120000Z" in b for b in bodies)


@pytest.mark.parametrize("args,err", [
    ({"calendar": "personal", "summary": "X", "start": "2026-11-20", "end": "2026-11-21"}, "all_day"),
    ({"calendar": "personal", "summary": "X",
      "start": "2026-11-16T09:00:00Z", "end": "2026-11-16T10:30:00+02:00"}, "offset style"),
])
def test_cal_create_rejected_before_any_request(nc, call, args, err):
    nc.handler = lambda req: httpx.Response(500, text="must not be called")
    res = call("nc_cal_create", args)
    assert res["ok"] is False and err in res["error"]
    assert nc.requests == []


def test_cal_create_consistent_offset_pair_stored_floating(nc, call):
    state = {}
    nc.handler = _put_get_state_handler(state)
    res = call("nc_cal_create", {
        "calendar": "personal", "summary": "X",
        "start": "2026-11-16T12:00:00+01:00", "end": "2026-11-16T13:00:00+01:00",
    })
    assert res["ok"] and res["verified"], res
    body = state[f"{CAL_DAV}/{res['uid']}.ics"]
    assert "DTSTART:20261116T120000" in body
    assert "DTEND:20261116T130000" in body
    assert "DTSTART:20261116T120000Z" not in body
    assert "DTEND:20261116T130000Z" not in body


_ICS_TIMED = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:uid-timed\r\nDTSTAMP:20261101T000000Z\r\n"
    "DTSTART:20261110T140000Z\r\nDTEND:20261110T150000Z\r\nSUMMARY:Timed\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n"
)
_ICS_Z = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:uid-z\r\nDTSTAMP:20261101T000000Z\r\n"
    "DTSTART:20261116T090000Z\r\nDTEND:20261116T100000Z\r\nSUMMARY:Z\r\n"
    "END:VEVENT\r\nEND:VCALENDAR\r\n"
)


@pytest.mark.parametrize("args,ics,err", [
    ({"calendar": "personal", "uid": "uid-timed", "start": "2026-11-20"}, _ICS_TIMED, "all_day"),
    ({"calendar": "personal", "uid": "uid-z", "end": "2026-11-16T10:30:00+02:00"}, _ICS_Z, "offset style"),
])
def test_cal_edit_rejected_before_put(nc, call, args, ics, err):
    state = {}
    _edit_handler(nc, state, ics, args["uid"])
    res = call("nc_cal_edit", args)
    assert res["ok"] is False and err in res["error"]
    assert nc.find("PUT", "") == []  # rejected before any write
    assert state == {}


def test_cal_list_defaults_use_config_timezone(monkeypatch):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    mock, call = _nc_with_settings(monkeypatch, {"server_timezone": "Europe/Berlin"})

    def h(req):
        assert req.method == "REPORT", f"unexpected {req.method} (detection must not fire)"
        return multistatus([])

    mock.handler = h
    res = call("nc_cal_list", {"calendar": "personal"})
    assert res["ok"], res
    berlin = ZoneInfo("Europe/Berlin")
    now_b = datetime.now(berlin)
    assert datetime.fromisoformat(res["from"]).utcoffset() == (now_b - timedelta(days=30)).utcoffset(), res["from"]
    assert datetime.fromisoformat(res["to"]).utcoffset() == (now_b + timedelta(days=90)).utcoffset(), res["to"]
    body = mock.find("REPORT", "calendars")[0].content.decode()
    m = re.search(r'start="(\d{8}T\d{6})(Z?)"', body)
    assert m and m.group(2) == ""  # floating Berlin wall time, no Z
    assert mock.find("PROPFIND", "calendars") == []


def test_cal_list_defaults_detect_server_tz(monkeypatch):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    mock, call = _nc_with_settings(monkeypatch, None)
    tz_xml = "<cal:calendar-timezone>BEGIN:VTIMEZONE\r\nTZID:Europe/Berlin\r\nEND:VTIMEZONE</cal:calendar-timezone>"

    def h(req):
        if req.method == "PROPFIND":
            return multistatus([("/remote.php/dav/calendars/bot/", tz_xml)])
        assert req.method == "REPORT"
        return multistatus([])

    mock.handler = h
    berlin = ZoneInfo("Europe/Berlin")
    now_b = datetime.now(berlin)
    for _ in range(2):
        res = call("nc_cal_list", {"calendar": "personal"})
        assert res["ok"], res
        assert datetime.fromisoformat(res["from"]).utcoffset() == (now_b - timedelta(days=30)).utcoffset(), res["from"]
    assert len(mock.find("PROPFIND", "calendars")) == 1  # detection cached per process


def test_cal_list_defaults_utc_fallback_when_undetectable(monkeypatch):
    mock, call = _nc_with_settings(monkeypatch, None)

    def h(req):
        if req.method == "PROPFIND":
            return httpx.Response(404, text="nf")
        assert req.method == "REPORT"
        return multistatus([])

    mock.handler = h
    res = call("nc_cal_list", {"calendar": "personal"})
    assert res["ok"], res
    assert res["from"].endswith("+00:00"), res["from"]
    body = mock.find("REPORT", "calendars")[0].content.decode()
    assert re.search(r'start="\d{8}T\d{6}Z"', body)  # UTC fallback -> Z suffix


def test_cal_list_defaults_invalid_setting_utc(monkeypatch):
    mock, call = _nc_with_settings(monkeypatch, {"server_timezone": "Not/AZone"})

    def h(req):
        assert req.method == "REPORT", f"unexpected {req.method} (invalid setting -> no detection)"
        return multistatus([])

    mock.handler = h
    res = call("nc_cal_list", {"calendar": "personal"})
    assert res["ok"], res
    assert res["from"].endswith("+00:00"), res["from"]
    assert mock.find("PROPFIND", "calendars") == []


def test_cal_list_explicit_args_pass_through(monkeypatch):
    mock, call = _nc_with_settings(monkeypatch, {"server_timezone": "Europe/Berlin"})

    def h(req):
        assert req.method == "REPORT", f"unexpected {req.method} (setting set -> no detection)"
        return multistatus([])

    mock.handler = h
    res = call("nc_cal_list", {"calendar": "personal", "from": "2026-11-01T00:00:00+02:00"})
    assert res["ok"], res
    assert res["from"] == "2026-11-01T00:00:00+02:00"  # echoed exactly as given
    body = mock.find("REPORT", "calendars")[0].content.decode()
    assert 'start="20261101T000000"' in body  # wall time kept, no Z, no conversion to 20261030T220000Z
    assert mock.find("PROPFIND", "calendars") == []


def test_cal_list_defaults_detect_server_tz_nested_vtimezone(monkeypatch):
    # RFC 4791 §5.2.2 shape: calendar-timezone contains a nested VTIMEZONE component
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    mock, call = _nc_with_settings(monkeypatch, None)
    tz_xml = (
        "<cal:calendar-timezone><VTIMEZONE>"
        "<BEGIN>VTIMEZONE</BEGIN><TZID>Europe/Berlin</TZID>"
        "<END>VTIMEZONE</END></VTIMEZONE></cal:calendar-timezone>"
    )

    def h(req):
        if req.method == "PROPFIND":
            return multistatus([("/remote.php/dav/calendars/bot/", tz_xml)])
        assert req.method == "REPORT"
        return multistatus([])

    mock.handler = h
    res = call("nc_cal_list", {"calendar": "personal"})
    assert res["ok"], res
    now_b = datetime.now(ZoneInfo("Europe/Berlin"))
    assert datetime.fromisoformat(res["from"]).utcoffset() == (now_b - timedelta(days=30)).utcoffset(), res["from"]


def test_cal_list_404_returns_missing_calendar_err_with_available(nc, call):
    home = "/remote.php/dav/calendars/bot"

    def h(req):
        if req.method == "REPORT":
            return httpx.Response(404, text="nf")
        if req.method == "PROPFIND" and req.url.path == home + "/":
            return multistatus([
                (f"{home}/", '<d:resourcetype><d:collection/></d:resourcetype><d:displayname>Calendars</d:displayname>'),
                (f"{home}/personal", '<d:resourcetype><d:collection/></d:resourcetype><d:displayname>Personal</d:displayname>'),
            ])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_cal_list", {"calendar": "nope"})
    assert res["ok"] is False
    assert res["calendar"] == "nope" and res["available"] == ["personal"]
    assert "not found" in res["error"]


def test_cal_create_404_returns_missing_calendar_err_with_available(nc, call):
    home = "/remote.php/dav/calendars/bot"

    def h(req):
        if req.method == "PUT":
            return httpx.Response(404, text="nf")
        if req.method == "PROPFIND" and req.url.path == home + "/":
            return multistatus([
                (f"{home}/tasks", '<d:resourcetype><d:collection/></d:resourcetype><d:displayname>Tasks</d:displayname>'),
            ])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_cal_create", {"calendar": "nope", "summary": "x", "start": "2026-11-10T14:00:00Z", "end": "2026-11-10T15:00:00Z"})
    assert res["ok"] is False
    assert res["calendar"] == "nope" and res["available"] == ["tasks"]
