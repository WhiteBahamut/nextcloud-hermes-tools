"""Client security: cache key covers password/timeout; redaction never leaks (review S3+S4)."""

import json

from nextcloud_tools import client


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
