"""Task handlers: list/create/complete/reopen with status and read-back verification."""

import httpx
from conftest import TASKS_DAV, multistatus


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
            (f"{TASKS_DAV}/a.ics", f"<cal:calendar-data>{vtodo('a', 'NEEDS-ACTION')}</cal:calendar-data>"),
            (f"{TASKS_DAV}/b.ics", f"<cal:calendar-data>{vtodo('b', 'COMPLETED')}</cal:calendar-data>"),
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
            (f"{TASKS_DAV}/a.ics", f"<cal:calendar-data>{vtodo('a', 'NEEDS-ACTION')}</cal:calendar-data>"),
            (f"{TASKS_DAV}/b.ics", f"<cal:calendar-data>{vtodo('b', 'COMPLETED')}</cal:calendar-data>"),
            (f"{TASKS_DAV}/c.ics", f"<cal:calendar-data>{vtodo('c', 'IN-PROCESS')}</cal:calendar-data>"),
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
    body = state[f"{TASKS_DAV}/{res['uid']}.ics"]
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
    assert "STATUS:IN-PROCESS" in state[f"{TASKS_DAV}/{res['uid']}.ics"]
    res = call("nc_task_create", {"calendar": "tasks", "summary": "S", "status": "COMPLETED"})
    assert res["ok"] and res["verified"] and res["status"] == "COMPLETED"
    body = state[f"{TASKS_DAV}/{res['uid']}.ics"]
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
            return multistatus([(f"{TASKS_DAV}/{uid}.ics",
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
    body = state[f"{TASKS_DAV}/{uid}.ics"]
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
            return multistatus([(f"{TASKS_DAV}/{uid}.ics",
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
    body = state[f"{TASKS_DAV}/{uid}.ics"]
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
            return multistatus([(f"{TASKS_DAV}/{uid}.ics",
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



def test_task_create_due_passthrough(nc, call):
    state = {}
    nc.handler = _put_get_state_handler(state)
    res = call("nc_task_create", {"calendar": "tasks", "summary": "A", "due": "2026-11-20T18:00:00+02:00"})
    assert res["ok"] and res["verified"], res
    body = state[f"{TASKS_DAV}/{res['uid']}.ics"]
    assert "DUE:20261120T180000" in body  # wall time kept, not converted to 170000Z
    assert "DUE:20261120T170000Z" not in body
    res = call("nc_task_create", {"calendar": "tasks", "summary": "B", "due": "2026-11-20"})
    assert res["ok"] and res["verified"], res
    body = state[f"{TASKS_DAV}/{res['uid']}.ics"]
    assert "DUE;VALUE=DATE:20261120" in body
