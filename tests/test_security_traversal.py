"""Path-traversal rejection: enc_path, nc_ocs, comments file_id (review S1)."""

import pytest

from nextcloud_tools import client


def test_enc_path_rejects_dot_segments():
    for bad in ("..", "/..", "a/../b", "/a/./b", "%2e%2e", "a/%2e%2e/b"):
        with pytest.raises(client.NcError) as ei:
            client.enc_path(bad)
        assert ei.value.status == 400


def test_enc_path_clean_segments_unchanged():
    assert client.enc_path("/a b/c.txt") == "/a%20b/c.txt"
    assert client.enc_path("/") == "/"


def test_dav_tool_path_traversal_rejected_before_request(nc, call):
    for bad in ("../../x", "/a/./b", "%2e%2e/x"):
        res = call("nc_file_get", {"path": bad})
        assert res["ok"] is False and res.get("status") == 400, bad
    assert nc.requests == []  # rejection never becomes an HTTP request


def test_nc_ocs_encoded_traversal_rejected_before_request(nc, call):
    for bad in ("apps/%2e%2e%2f%2e%2e%2fstatus.php", "apps/..%2fsecret", "a%2f..%2fb"):
        res = call("nc_ocs", {"method": "GET", "path": bad})
        assert res["ok"] is False and "traversal" in res["error"], bad
    assert nc.requests == []


def test_comments_file_id_must_be_numeric(nc, call):
    res = call("nc_comments", {"action": "list", "file_id": "12/../../x"})
    assert res["ok"] is False and res.get("status") == 400
    assert nc.requests == []
