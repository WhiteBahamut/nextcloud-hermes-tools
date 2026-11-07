from datetime import datetime

import httpx
from conftest import multistatus
from nextcloud_tools import ical

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
        exdates=[("20261104T090000", {})],
    )
    assert [o.day for o in occ] == [3, 5]  # 4th excluded via EXDATE


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
    assert res["ok"] and [t["uid"] for t in res["tasks"]] == ["a"]
    res = call("nc_task_list", {"calendar": "tasks", "include_completed": True})
    assert sorted(t["uid"] for t in res["tasks"]) == ["a", "b"]
    assert res["tasks"][0]["due"] == "20261120"


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
