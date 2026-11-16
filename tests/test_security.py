"""Security: redaction, secret cache key, and path-traversal rejection."""

import base64
import json

import pytest

from nextcloud_tools import client


# --- client security: cache key covers password/timeout; redaction never leaks ---


def test_get_client_rebuilds_on_password_and_timeout_change(monkeypatch):
    from conftest import FakeCtx

    monkeypatch.setenv("TALK_SERVER_URL", "https://nc.example")
    monkeypatch.setenv("TALK_USER", "bot")
    monkeypatch.setenv("TALK_APP_PASSWORD", "pw-one")
    monkeypatch.setattr(client, "_CLIENT", None)
    monkeypatch.setattr(client, "_CLIENT_KEY", None)
    client.configure(FakeCtx())
    try:
        c1 = client.get_client()
        assert client.get_client() is c1  # same key -> cached
        assert client._CLIENT_KEY == ("https://nc.example", "bot", "pw-one", "", 30.0)
        monkeypatch.setenv("TALK_APP_PASSWORD", "pw-two")
        c2 = client.get_client()
        assert c2 is not c1 and client._CLIENT_KEY[2] == "pw-two"
        client.configure(FakeCtx({"request_timeout": 5.0}))
        c3 = client.get_client()
        assert c3 is not c2 and client._CLIENT_KEY[4] == 5.0
    finally:
        client.configure(FakeCtx())


def test_redact_strips_url_userinfo(nc):
    out = client.redact("connect to https://bot:s3cret-pw@nc.example/remote.php failed")
    assert out == "connect to https://***:***@nc.example/remote.php failed"
    assert "s3cret-pw" not in out and "bot" not in out


def test_redact_leaves_clean_urls_alone(nc):
    assert client.redact("https://nc.example/remote.php/x") == "https://nc.example/remote.php/x"


def test_redact_strips_urlencoded_password(nc, monkeypatch):
    monkeypatch.setenv("NC_APP_PASSWORD", "pw with space")
    out = client.redact("leak pw%20with%20space and pw with space")
    assert "pw%20with%20space" not in out and "pw with space" not in out
    assert out == "leak *** and ***"


def test_redact_never_raises_when_lookup_fails(monkeypatch):
    def boom(name):
        raise RuntimeError("secret scope down")

    monkeypatch.setattr(client, "_lookup", boom)
    out = client.redact("Authorization: Basic abc123")
    assert "abc123" not in out and "Authorization:" in out


def test_err_suppresses_message_if_redact_fails(monkeypatch):
    def boom(text):
        raise RuntimeError("scope down")

    monkeypatch.setattr(client, "redact", boom)
    res = json.loads(client.err("raw secret text"))
    assert res["ok"] is False and res["error"] == "internal error (message suppressed)"


# --- redaction through redact()/err() (moved from test_client) ---


def test_redaction_strips_password_b64_and_auth_header(nc):
    token = base64.b64encode(b"bot:s3cret-pw").decode()
    text = f"connect failed bot:s3cret-pw; Authorization: Basic {token}; Bearer {token}"
    out = client.redact(text)
    assert "s3cret-pw" not in out
    assert token not in out
    assert "Authorization: Basic ***" in out
    assert "Bearer ***" in out


def test_err_json_redacts_password(nc):
    res = json.loads(client.err("failed with s3cret-pw inside"))
    assert res["ok"] is False
    assert "s3cret-pw" not in res["error"]
    assert "***" in res["error"]


def test_redaction_strips_both_spellings(nc, monkeypatch):
    monkeypatch.setenv("NC_APP_PASSWORD", "nc-pw")
    assert client.redact("leak nc-pw and s3cret-pw") == "leak *** and ***"


# --- path traversal: enc_path, DAV tools, nc_ocs, comments file_id ---


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


# --- nc_ocs traversal gating (moved from test_client) ---


def test_nc_ocs_traversal_rejected_without_request(nc, call):
    for bad in ("/apps/x", "apps/../secret", "a/../../b", ".."):
        res = call("nc_ocs", {"path": bad})
        assert res["ok"] is False, bad
    assert nc.requests == []  # traversal never becomes a request


def test_nc_ocs_traversal_rejected_for_every_method(nc, call):
    for m in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        res = call("nc_ocs", {"method": m, "path": "apps/../secret"})
        assert res["ok"] is False and "traversal" in res["error"], m
    assert nc.requests == []  # traversal never becomes a request, any method
