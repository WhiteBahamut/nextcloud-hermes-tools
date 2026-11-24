"""Search: concurrent providers, per-provider error isolation, defaults, local file filter."""

import threading
import time

import conftest
from conftest import ocs_err, ocs_ok


def test_search_providers_run_concurrently_and_keep_order(nc, call):
    state = {"cur": 0, "max": 0}
    lock = threading.Lock()

    def h(req):
        with lock:
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
        time.sleep(0.05)
        with lock:
            state["cur"] -= 1
        if "deck" in req.url.path:
            return ocs_err(404, "provider not installed")
        return ocs_ok([{"id": "1", "name": "hit"}])

    nc.handler = h
    res = call("nc_search", {"term": "x", "providers": ["files", "fulltextsearch", "deck"], "limit": 5})
    assert res["ok"] and res["count"] == 3
    assert state["max"] > 1  # requests actually overlapped
    assert [r["provider"] for r in res["results"]] == ["files", "fulltextsearch", "deck"]
    assert "error" in res["results"][2]  # per-provider error entry preserved


def test_search_provider_failure_isolated(nc, call):
    def h(req):
        if "search/providers/files/" in req.url.path:
            return ocs_ok([{"id": "1", "name": "a.txt", "link": "https://nc.example/f/1"}])
        return ocs_err(404, "provider not installed on this server")

    nc.handler = h
    res = call("nc_search", {"term": "a", "providers": ["files", "deck"], "limit": 5})
    assert res["ok"] and res["count"] == 2
    by_provider = {r["provider"]: r for r in res["results"]}
    assert by_provider["files"]["name"] == "a.txt"
    assert "error" in by_provider["deck"]  # per-provider error, whole call still ok
    q = nc.requests[0].url.params  # term/limit passed as query params (httpx encodes)
    assert q["term"] == "a" and q["limit"] == "5"


def test_search_provider_result_capped_client_side(nc, call):
    # provider ignores the limit query param and returns 10 entries
    nc.handler = lambda req: ocs_ok([{"id": str(i), "name": f"hit{i}"} for i in range(10)])
    res = call("nc_search", {"term": "x", "providers": ["files"], "limit": 3})
    assert res["ok"] and res["count"] == 3
    assert [r["id"] for r in res["results"]] == ["0", "1", "2"]
    assert nc.requests[0].url.params["limit"] == "3"  # still sent server-side


def test_search_defaults_come_from_settings(nc):
    _ctx, call = conftest.make_caller({"default_search_providers": ["files"], "max_results": 7})

    def h(req):
        assert "search/providers/files/" in req.url.path
        assert req.url.params["limit"] == "7"
        return ocs_ok([])

    nc.handler = h
    res = call("nc_search", {"term": "x"})
    assert res["ok"] and res["results"] == []


def test_file_search_local_filter_with_limit(nc, call):
    from conftest import multistatus

    nc.handler = lambda req: multistatus([
        (f"/remote.php/dav/files/bot/", '<d:resourcetype><d:collection/></d:resourcetype>'),
        (f"/remote.php/dav/files/bot/report-2026.pdf", '<d:resourcetype/><d:getcontentlength>10</d:getcontentlength>'),
        (f"/remote.php/dav/files/bot/Report-final.txt", '<d:resourcetype/><d:getcontentlength>3</d:getcontentlength>'),
        (f"/remote.php/dav/files/bot/other.bin", '<d:resourcetype/><d:getcontentlength>1</d:getcontentlength>'),
    ])
    res = call("nc_file_search", {"term": "REPORT", "path": "/", "limit": 100})
    assert res["ok"]
    assert nc.requests[0].headers["Depth"] == "infinity"
    names = {r["name"] for r in res["results"]}
    assert names == {"report-2026.pdf", "Report-final.txt"}  # case-insensitive
