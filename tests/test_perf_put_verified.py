"""Writes verified via the OC-Checksum response header, GET read-back as fallback (review P1)."""

import hashlib

import httpx


def test_put_verified_uses_oc_checksum_header_without_get(nc, call):
    def h(req):
        if req.method == "PUT":
            assert req.headers["OC-Checksum"].startswith("SHA256:")
            digest = hashlib.sha256(req.content).hexdigest()
            return httpx.Response(201, headers={"OC-Checksum": f"SHA256:{digest}"})
        return httpx.Response(404, text="nf")  # a GET here would fail the call

    nc.handler = h
    res = call("nc_file_put", {"path": "/x.txt", "content": "hello"})
    assert res["ok"] and res["verified"]
    assert [r.method for r in nc.requests] == ["PUT"]  # no read-back re-download


def test_put_verified_checksum_mismatch_fails(nc, call):
    def h(req):
        if req.method == "PUT":
            return httpx.Response(201, headers={"OC-Checksum": "SHA256:" + "0" * 64})
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_put", {"path": "/x.txt", "content": "hello"})
    assert res["ok"] is False and res.get("status") == 500 and "OC-Checksum" in res["error"]


def test_put_verified_falls_back_to_get_when_header_absent(nc, call):
    state = {}

    def h(req):
        if req.method == "PUT":
            state[req.url.path] = req.content
            return httpx.Response(201)  # no OC-Checksum echo
        if req.method == "GET":
            return httpx.Response(200, content=state[req.url.path])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_put", {"path": "/x.txt", "content": "hello"})
    assert res["ok"] and res["verified"]
    assert [r.method for r in nc.requests] == ["PUT", "GET"]
