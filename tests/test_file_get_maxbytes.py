"""nc_file_get caps content at max_bytes with truncated flag and full size (review A1)."""

import base64 as b64

import httpx


def test_file_get_truncates_to_default_max_bytes(nc, call):
    nc.handler = lambda req: httpx.Response(200, content=b"x" * 300_000, headers={"etag": '"e1"'})
    res = call("nc_file_get", {"path": "/big.txt"})
    assert res["ok"] and res["truncated"] is True and res["max_bytes"] == 100000
    assert res["size"] == 300_000 and len(res["content"]) == 100_000 and res["etag"] == '"e1"'


def test_file_get_max_bytes_zero_is_unlimited(nc, call):
    nc.handler = lambda req: httpx.Response(200, content=b"x" * 300_000)
    res = call("nc_file_get", {"path": "/big.txt", "max_bytes": 0})
    assert res["ok"] and "truncated" not in res and len(res["content"]) == 300_000


def test_file_get_negative_max_bytes_rejected_before_request(nc, call):
    res = call("nc_file_get", {"path": "/a.txt", "max_bytes": -5})
    assert res["ok"] is False and nc.requests == []


def test_file_get_truncated_binary_slice_falls_back_to_base64(nc, call):
    nc.handler = lambda req: httpx.Response(200, content=b"\xff\xfe" * 100_000)
    res = call("nc_file_get", {"path": "/bin.dat", "max_bytes": 100})
    assert res["ok"] and res["truncated"] is True and res["size"] == 200_000
    assert "content" not in res and b64.b64decode(res["content_base64"]) == b"\xff\xfe" * 50
