"""Shares: list/create/delete/edit with read-back verification; read-only default."""

import httpx
from conftest import ocs_err, ocs_ok


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


def test_share_delete_verified_404(nc, call):
    def h(req):
        if req.method == "DELETE":
            return ocs_ok([])
        return ocs_err(404, "share not found")

    nc.handler = h
    res = call("nc_share_delete", {"id": 5})
    assert res["ok"] and res["deleted"] and res["verified"]
    assert nc.requests[1].url.path.endswith("/shares/5")


def test_share_edit_puts_only_provided_fields_and_verifies(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PUT" and p.endswith("/shares/5"):
            return ocs_ok({"id": 5})
        if req.method == "GET" and p.endswith("/shares/5"):
            return ocs_ok({"id": 5, "permissions": 31, "note": "hi", "expiration": "2026-12-31T00:00:00+00:00"})
        return ocs_err(404, "nf")

    nc.handler = h
    res = call("nc_share_edit", {"id": 5, "permissions": 31, "note": "hi", "expire_date": "2026-12-31"})
    assert res["ok"] and res["verified"] and res["id"] == 5
    put = nc.requests[0]
    assert put.method == "PUT" and put.url.path.endswith("/shares/5")
    body = put.content.decode()
    assert "permissions=31" in body and "note=hi" in body and "expireDate=2026-12-31" in body
    assert "password" not in body  # not provided -> not sent
    assert nc.requests[1].method == "GET"


def test_share_edit_readback_mismatch_fails(nc, call):
    def h(req):
        if req.method == "PUT":
            return ocs_ok({"id": 5})
        return ocs_ok({"id": 5, "permissions": 1})  # read-back shows old permissions

    nc.handler = h
    res = call("nc_share_edit", {"id": 5, "permissions": 31})
    assert res["ok"] is False and "verification" in res["error"]


def test_share_edit_password_only_verifies_via_get(nc, call):
    def h(req):
        if req.method == "PUT":
            return ocs_ok({"id": 5})
        return ocs_ok({"id": 5})  # password never echoed; GET success is the verification

    nc.handler = h
    res = call("nc_share_edit", {"id": 5, "password": "s3cret"})
    assert res["ok"] and res["verified"]
    assert "password=s3cret" in nc.requests[0].content.decode()


def test_share_edit_no_fields_rejected_before_request(nc, call):
    nc.handler = lambda req: httpx.Response(500)
    res = call("nc_share_edit", {"id": 5})
    assert res["ok"] is False and nc.requests == []
