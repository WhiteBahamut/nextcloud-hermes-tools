import conftest
from conftest import ocs_err, ocs_ok


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


def test_share_list(nc, call):
    nc.handler = lambda req: ocs_ok([{"id": 1, "share_type": 0, "path": "/a.txt"}])
    res = call("nc_share_list", {"path": "/a.txt"})
    assert res["ok"] and res["count"] == 1
    assert nc.requests[0].url.params["path"] == "/a.txt"


def test_share_create_verified_via_readback(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "POST" and p.endswith("/shares"):
            return ocs_ok({"id": 99, "share_type": 0, "path": "/a.txt"})
        if req.method == "GET" and p.endswith("/shares"):
            return ocs_ok([{"id": 99, "path": "/a.txt"}])
        return ocs_err(404, "nf")

    nc.handler = h
    res = call("nc_share_create", {"path": "/a.txt", "share_with": "alice", "permissions": 31})
    assert res["ok"] and res["verified"] and res["id"] == 99
    body = nc.requests[0].content.decode()  # form-encoded, not JSON
    assert "shareWith=alice" in body and "path=%2Fa.txt" in body and "permissions=31" in body


def test_share_create_readback_missing_fails(nc, call):
    nc.handler = lambda req: ocs_ok({"id": 99}) if req.method == "POST" else ocs_ok([])
    res = call("nc_share_create", {"path": "/a.txt", "share_with": "alice"})
    assert res["ok"] is False and "verification" in res["error"]


def test_share_delete_verified_404(nc, call):
    def h(req):
        if req.method == "DELETE":
            return ocs_ok([])
        return ocs_err(404, "share not found")

    nc.handler = h
    res = call("nc_share_delete", {"id": 5})
    assert res["ok"] and res["deleted"] and res["verified"]
    assert nc.requests[1].url.path.endswith("/shares/5")
