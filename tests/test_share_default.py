"""Share creation defaults to read-only permissions (review S5)."""

from conftest import ocs_ok


def test_share_create_defaults_to_read_only(nc, call):
    def h(req):
        if req.method == "POST" and req.url.path.endswith("/shares"):
            return ocs_ok({"id": 7, "path": "/a.txt"})
        return ocs_ok([{"id": 7, "path": "/a.txt"}])

    nc.handler = h
    res = call("nc_share_create", {"path": "/a.txt", "share_with": "alice"})
    assert res["ok"] and res["verified"] and res["id"] == 7
    body = nc.requests[0].content.decode()
    assert "permissions=1" in body  # least-privilege default, not 31
