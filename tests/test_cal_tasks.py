from datetime import datetime
import re

import httpx
from conftest import MockNc, make_caller, multistatus
from nextcloud_tools import client, ical, tools_cal

CAL = "/remote.php/dav/calendars/bot/personal"
TASKS = "/remote.php/dav/calendars/bot/tasks"


# --- RRULE expansion (ical.py) -----------------------------------------------------


def test_rrule_daily_count():
    occ = ical.expand_rrule(datetime(2026, 11, 2, 9), "FREQ=DAILY;COUNT=3")
    assert [o.day for o in occ] == [2, 3, 4]


def test_rrule_daily_interval():
    occ = ical.expand_rrule(datetime(2026, 11, 2, 9), "FREQ=DAILY;INTERVAL=2;COUNT=3")
    assert [o.day for o in occ] == [2, 4, 6]


def test_rrule_weekly_byday():
    # 2026-11-02 is a Monday
    occ = ical.expand_rrule(datetime(2026, 11, 2, 9), "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4")
    assert [o.strftime("%a") for o in occ] == ["Mon", "Wed", "Mon", "Wed"]


def test_rrule_monthly_until_skips_invalid_days():
    occ = ical.expand_rrule(datetime(2026, 1, 31, 9), "FREQ=MONTHLY;UNTIL=20260430T235959Z")
    assert [o.date().isoformat() for o in occ] == ["2026-01-31", "2026-03-31"]  # Feb 31 / Apr 31 skipped


def test_rrule_exdate_and_range_filter():
    occ = ical.expand_rrule(
        datetime(2026, 11, 2, 9), "FREQ=DAILY;COUNT=5",
        range_start=datetime(2026, 11, 3), range_end=datetime(2026, 11, 5, 23, 59),
        exdates=[({}, "20261104T090000")],
    )
    assert [o.day for o in occ] == [3, 5]  # 4th excluded via EXDATE


def test_rrule_exdate_from_parse_ics():
    # regression: parse_ics stores props as (params, value); expand_rrule must unpack in that order
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x1\r\nDTSTAMP:20261101T000000Z\r\n"
        "DTSTART;TZID=Europe/Berlin:20261102T090000\r\nDTEND;TZID=Europe/Berlin:20261102T100000\r\n"
        "RRULE:FREQ=DAILY;COUNT=5\r\nEXDATE;TZID=Europe/Berlin:20261104T090000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    vevent = ical.first_component(ical.parse_ics(ics), "VEVENT")
    dt_p, dt_v = ical.prop_with_params(vevent, "DTSTART")
    occ = ical.expand_rrule(
        ical.parse_dt(dt_v, dt_p),
        ical.prop(vevent, "RRULE"),
        exdates=vevent["props"]["EXDATE"],
    )
    assert [o.day for o in occ] == [2, 3, 5, 6]  # 4th excluded, no exception


def test_event_dict_exdate_end_to_end():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x2\r\nDTSTAMP:20261101T000000Z\r\n"
        "DTSTART:20261102T090000Z\r\nDTEND:20261102T100000Z\r\n"
        "RRULE:FREQ=DAILY;COUNT=4\r\nEXDATE:20261104T090000Z\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    vevent = ical.first_component(ical.parse_ics(ics), "VEVENT")
    ev = tools_cal._event_dict(vevent, None, None)
    assert [o["start"][:10] for o in ev["occurrences"]] == ["2026-11-02", "2026-11-03", "2026-11-05"]


def test_rrule_capped_at_500():
    occ = ical.expand_rrule(datetime(2026, 1, 1, 9), "FREQ=DAILY", range_end=datetime(2030, 1, 1))
    assert len(occ) == 500


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
        return multistatus([(f"{CAL}/e1.ics", f"<cal:calendar-data>{ev}</cal:calendar-data>")])

    nc.handler = h
    res = call("nc_cal_list", {"calendar": "personal", "from": "2026-11-01T00:00:00Z", "to": "2026-11-30T23:59:59Z"})
    assert res["ok"]
    event = res["events"][0]
    assert event["summary"] == "Meeting" and event["uid"] == "e1"
    assert len(event["occurrences"]) == 3
    assert event["occurrences"][0]["end"].startswith("2026-11-10T15:00:00")


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
    body = state[f"{CAL}/{res['uid']}.ics"]
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
            return multistatus([(f"{CAL}/{uid}.ics",
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
    body = state[f"{CAL}/{res['uid']}.ics"]
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
    assert "VALARM" not in state[f"{CAL}/{res['uid']}.ics"]


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
    body = state[f"{CAL}/{uid}.ics"]
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
    assert "BEGIN:VALARM" not in state[f"{CAL}/{uid}.ics"]


def test_cal_edit_preserves_valarm_on_other_edits(nc, call):
    uid = "uid-rem"
    state = {}
    _edit_handler(nc, state, ALARM_ICS, uid)
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "summary": "new"})
    assert res["ok"] and res["verified"]
    body = state[f"{CAL}/{uid}.ics"]
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
    body = state[f"{CAL}/{uid}.ics"]
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
            return multistatus([(f"{CAL}/{uid}.ics",
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
            return multistatus([(f"{CAL}/{uid}.ics",
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
            return multistatus([(f"{CAL}/{uid}.ics",
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
    assert "SUMMARY:new" in state[f"{CAL}/{uid}.ics"]
    assert "UID:uid-1" in state[f"{CAL}/{uid}.ics"]


def test_cal_delete_if_match_and_404_verify(nc, call):
    uid = "uid-9"
    state = {f"{CAL}/{uid}.ics": "x"}

    def h(req):
        p = req.url.path
        if req.method == "REPORT":
            return multistatus([(f"{CAL}/{uid}.ics", '<d:getetag>&amp;quot;e9&amp;quot;</d:getetag>')])
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


# --- tasks ---------------------------------------------------------------------------


def test_task_list_filters_completed(nc, call):
    def vtodo(uid, status):
        return (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\n"
            f"UID:{uid}\r\nDTSTAMP:20261101T000000Z\r\nSUMMARY:t-{uid}\r\nSTATUS:{status}\r\nDUE;VALUE=DATE:20261120\r\n"
            "END:VTODO\r\nEND:VCALENDAR\r\n"
        )

    def h(req):
        return multistatus([
            (f"{TASKS}/a.ics", f"<cal:calendar-data>{vtodo('a', 'NEEDS-ACTION')}</cal:calendar-data>"),
            (f"{TASKS}/b.ics", f"<cal:calendar-data>{vtodo('b', 'COMPLETED')}</cal:calendar-data>"),
        ])

    nc.handler = h
    res = call("nc_task_list", {"calendar": "tasks"})
    assert res["ok"] and sorted(t["uid"] for t in res["tasks"]) == ["a", "b"]
    res = call("nc_task_list", {"calendar": "tasks", "include_completed": False})
    assert [t["uid"] for t in res["tasks"]] == ["a"]
    assert res["tasks"][0]["due"] == "20261120"


def test_task_list_stats(nc, call):
    def vtodo(uid, status):
        return (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\n"
            f"UID:{uid}\r\nDTSTAMP:20261101T000000Z\r\nSUMMARY:t-{uid}\r\nSTATUS:{status}\r\n"
            "END:VTODO\r\nEND:VCALENDAR\r\n"
        )

    def h(req):
        return multistatus([
            (f"{TASKS}/a.ics", f"<cal:calendar-data>{vtodo('a', 'NEEDS-ACTION')}</cal:calendar-data>"),
            (f"{TASKS}/b.ics", f"<cal:calendar-data>{vtodo('b', 'COMPLETED')}</cal:calendar-data>"),
            (f"{TASKS}/c.ics", f"<cal:calendar-data>{vtodo('c', 'IN-PROCESS')}</cal:calendar-data>"),
        ])

    nc.handler = h
    res = call("nc_task_list", {"calendar": "tasks"})
    assert res["ok"] and res["stats"] == {"total": 3, "open": 2, "closed": 1} and res["count"] == 3
    res = call("nc_task_list", {"calendar": "tasks", "include_completed": False})
    assert res["count"] == 2 and [t["uid"] for t in res["tasks"]] == ["a", "c"]
    assert res["stats"] == {"total": 3, "open": 2, "closed": 1}
    res = call("nc_task_list", {"calendar": "tasks", "limit": 1})
    assert res["count"] == 1 and res["stats"]["total"] == 3


def test_task_create_verified(nc, call):
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
    res = call("nc_task_create", {"calendar": "tasks", "summary": "Do it", "due": "2026-11-20", "priority": 1})
    assert res["ok"] and res["verified"]
    body = state[f"{TASKS}/{res['uid']}.ics"]
    assert "STATUS:NEEDS-ACTION" in body and "DUE;VALUE=DATE:20261120" in body and "PRIORITY:1" in body


def test_task_create_initial_status(nc, call):
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
    res = call("nc_task_create", {"calendar": "tasks", "summary": "S", "status": "in-process"})
    assert res["ok"] and res["verified"] and res["status"] == "IN-PROCESS"
    assert "STATUS:IN-PROCESS" in state[f"{TASKS}/{res['uid']}.ics"]
    res = call("nc_task_create", {"calendar": "tasks", "summary": "S", "status": "COMPLETED"})
    assert res["ok"] and res["verified"] and res["status"] == "COMPLETED"
    body = state[f"{TASKS}/{res['uid']}.ics"]
    assert "STATUS:COMPLETED" in body and "PERCENT-COMPLETE:100" in body and "COMPLETED:" in body


def test_task_create_invalid_status(nc, call):
    def h(req):
        return httpx.Response(500, text="must not be called")

    nc.handler = h
    res = call("nc_task_create", {"calendar": "tasks", "summary": "S", "status": "bogus"})
    assert res["ok"] is False and "invalid status" in res["error"]
    assert nc.requests == []


def test_task_complete_sets_status_and_completed(nc, call):
    uid = "task-1"
    vtodo = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:task-1\r\nDTSTAMP:20261101T000000Z\r\n"
        "SUMMARY:Do\r\nSTATUS:NEEDS-ACTION\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
    )
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "REPORT":
            return multistatus([(f"{TASKS}/{uid}.ics",
                                 f'<d:getetag>&amp;quot;e&amp;quot;</d:getetag><cal:calendar-data>{vtodo}</cal:calendar-data>')])
        if req.method == "GET":
            return httpx.Response(200, text=state.get(p, vtodo))
        if req.method == "PUT":
            state[p] = req.content.decode()
            return httpx.Response(204)
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_task_complete", {"calendar": "tasks", "uid": uid})
    assert res["ok"] and res["status"] == "COMPLETED" and res["verified"]
    body = state[f"{TASKS}/{uid}.ics"]
    assert "STATUS:COMPLETED" in body and "COMPLETED:" in body and "PERCENT-COMPLETE:100" in body
    put = nc.find("PUT", "")[0]
    assert put.headers["If-Match"] == '"e"'


def test_task_reopen_clears_completed_and_readback(nc, call):
    uid = "task-1"
    vtodo = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:task-1\r\nDTSTAMP:20261101T000000Z\r\n"
        "SUMMARY:Do\r\nSTATUS:COMPLETED\r\nCOMPLETED:20261105T000000Z\r\nPERCENT-COMPLETE:100\r\n"
        "END:VTODO\r\nEND:VCALENDAR\r\n"
    )
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "REPORT":
            return multistatus([(f"{TASKS}/{uid}.ics",
                                 f'<d:getetag>&amp;quot;e&amp;quot;</d:getetag><cal:calendar-data>{vtodo}</cal:calendar-data>')])
        if req.method == "GET":
            return httpx.Response(200, text=state.get(p, vtodo))
        if req.method == "PUT":
            state[p] = req.content.decode()
            return httpx.Response(204)
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_task_reopen", {"calendar": "tasks", "uid": uid})
    assert res["ok"] and res["status"] == "NEEDS-ACTION" and res["verified"]
    body = state[f"{TASKS}/{uid}.ics"]
    assert "STATUS:NEEDS-ACTION" in body and "PERCENT-COMPLETE:0" in body and "COMPLETED:" not in body
    put = nc.find("PUT", "")[0]
    assert put.headers["If-Match"] == '"e"'


def test_task_reopen_verification_mismatch(nc, call):
    uid = "task-2"
    vtodo = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:task-2\r\nDTSTAMP:20261101T000000Z\r\n"
        "SUMMARY:Do\r\nSTATUS:COMPLETED\r\nCOMPLETED:20261105T000000Z\r\nPERCENT-COMPLETE:100\r\n"
        "END:VTODO\r\nEND:VCALENDAR\r\n"
    )

    def h(req):
        p = req.url.path
        if req.method == "REPORT":
            return multistatus([(f"{TASKS}/{uid}.ics",
                                 f'<d:getetag>&amp;quot;e&amp;quot;</d:getetag><cal:calendar-data>{vtodo}</cal:calendar-data>')])
        if req.method == "GET":
            return httpx.Response(200, text=vtodo)  # PUT never lands -> read-back mismatch
        if req.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_task_reopen", {"calendar": "tasks", "uid": uid})
    assert res["ok"] is False and "reopen verification failed" in res["error"]


def test_task_404_lists_available_calendars(nc, call):
    home = "/remote.php/dav/calendars/bot"
    collection = "<d:resourcetype><d:collection/></d:resourcetype>"

    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p.rstrip("/") == home:
            return multistatus([
                (f"{home}/", collection),
                (f"{home}/personal/", collection),
                (f"{home}/tasks/", collection),
                (f"{home}/edeka_shared_by_Fabian/", collection),
            ])
        if req.method == "REPORT" and p.rstrip("/") == f"{home}/missing":
            return httpx.Response(404, text="nf")
        if req.method == "REPORT":
            return multistatus([])  # existing calendar, UID not found
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_task_list", {"calendar": "missing"})
    assert res["ok"] is False
    assert "calendar 'missing' not found" in res["error"]
    assert "edeka_shared_by_Fabian" in res["error"]
    assert res["available"] == ["edeka_shared_by_Fabian", "personal", "tasks"]
    res = call("nc_task_complete", {"calendar": "missing", "uid": "x"})
    assert res["ok"] is False and "calendar 'missing' not found" in res["error"]
    assert res["available"] == ["edeka_shared_by_Fabian", "personal", "tasks"]
    res = call("nc_task_complete", {"calendar": "tasks", "uid": "x"})
    assert res["ok"] is False and "no VTODO with UID x" in res["error"]
    assert "available calendars" not in res["error"]


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
        body = state[f"{CAL}/{res['uid']}.ics"]
        assert expected in body, (start, body)
    # the +02:00 wall time must NOT have been converted to UTC
    bodies = list(state.values())
    assert not any("DTSTART:20261110T120000Z" in b for b in bodies)


def test_cal_create_date_only_without_all_day_rejected(nc, call):
    nc.handler = lambda req: httpx.Response(500, text="must not be called")
    res = call("nc_cal_create", {
        "calendar": "personal", "summary": "X",
        "start": "2026-11-20", "end": "2026-11-21",
    })
    assert res["ok"] is False
    assert "all_day" in res["error"]
    assert nc.requests == []


def test_cal_create_mixed_offset_styles_rejected(nc, call):
    nc.handler = lambda req: httpx.Response(500, text="must not be called")
    res = call("nc_cal_create", {
        "calendar": "personal", "summary": "X",
        "start": "2026-11-16T09:00:00Z", "end": "2026-11-16T10:30:00+02:00",
    })
    assert res["ok"] is False
    assert "offset style" in res["error"]
    assert nc.requests == []


def test_cal_create_consistent_offset_pair_stored_floating(nc, call):
    state = {}
    nc.handler = _put_get_state_handler(state)
    res = call("nc_cal_create", {
        "calendar": "personal", "summary": "X",
        "start": "2026-11-16T12:00:00+01:00", "end": "2026-11-16T13:00:00+01:00",
    })
    assert res["ok"] and res["verified"], res
    body = state[f"{CAL}/{res['uid']}.ics"]
    assert "DTSTART:20261116T120000" in body
    assert "DTEND:20261116T130000" in body
    assert "DTSTART:20261116T120000Z" not in body
    assert "DTEND:20261116T130000Z" not in body


def test_cal_edit_date_only_on_timed_event_rejected(nc, call):
    uid = "uid-timed"
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:uid-timed\r\nDTSTAMP:20261101T000000Z\r\n"
        "DTSTART:20261110T140000Z\r\nDTEND:20261110T150000Z\r\nSUMMARY:Timed\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    state = {}
    _edit_handler(nc, state, ics, uid)
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "start": "2026-11-20"})
    assert res["ok"] is False
    assert "all_day" in res["error"]
    assert nc.find("PUT", "") == []
    assert state == {}


def test_cal_edit_mixed_new_end_against_z_start_rejected(nc, call):
    uid = "uid-z"
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:uid-z\r\nDTSTAMP:20261101T000000Z\r\n"
        "DTSTART:20261116T090000Z\r\nDTEND:20261116T100000Z\r\nSUMMARY:Z\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    state = {}
    _edit_handler(nc, state, ics, uid)
    res = call("nc_cal_edit", {"calendar": "personal", "uid": uid, "end": "2026-11-16T10:30:00+02:00"})
    assert res["ok"] is False
    assert "offset style" in res["error"]
    assert nc.find("PUT", "") == []


def test_task_create_due_passthrough(nc, call):
    state = {}
    nc.handler = _put_get_state_handler(state)
    res = call("nc_task_create", {"calendar": "tasks", "summary": "A", "due": "2026-11-20T18:00:00+02:00"})
    assert res["ok"] and res["verified"], res
    body = state[f"{TASKS}/{res['uid']}.ics"]
    assert "DUE:20261120T180000" in body  # wall time kept, not converted to 170000Z
    assert "DUE:20261120T170000Z" not in body
    res = call("nc_task_create", {"calendar": "tasks", "summary": "B", "due": "2026-11-20"})
    assert res["ok"] and res["verified"], res
    body = state[f"{TASKS}/{res['uid']}.ics"]
    assert "DUE;VALUE=DATE:20261120" in body


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
