import base64
import json

import httpx
import pytest
from conftest import ocs_err, ocs_ok
from nextcloud_tools import client


def test_ocs_envelope_ok(nc):
    nc.handler = lambda req: ocs_ok({"hello": 1})
    assert client.ocs("GET", "apps/x") == {"hello": 1}
    req = nc.requests[0]
    assert req.url.path == "/ocs/v2.php/apps/x"
    assert req.headers["OCS-APIRequest"] == "true"


def test_ocs_envelope_error_raises_ncerror(nc):
    nc.handler = lambda req: ocs_err(404, "no such app")
    with pytest.raises(client.NcError) as ei:
        client.ocs("GET", "apps/nope")
    assert ei.value.status == 404
    assert "no such app" in ei.value.message


def test_ocs_non_json_response(nc):
    nc.handler = lambda req: httpx.Response(502, text="<html>bad gateway</html>")
    with pytest.raises(client.NcError) as ei:
        client.ocs("GET", "apps/x")
    assert ei.value.status == 502


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


def test_propfind_accepts_200_and_207_and_sends_depth(nc):
    nc.handler = lambda req: httpx.Response(207, text="<d:multistatus xmlns:d='DAV:'/>")
    client.propfind("/remote.php/dav/files/bot/", depth=1)
    nc.handler = lambda req: httpx.Response(200, text="<d:multistatus xmlns:d='DAV:'/>")
    client.propfind("/remote.php/dav/files/bot/", depth=0)
    assert nc.requests[0].headers["Depth"] == "1"
    assert nc.requests[1].headers["Depth"] == "0"


def test_propfind_rejects_other_status(nc):
    nc.handler = lambda req: httpx.Response(500, text="boom")
    with pytest.raises(client.NcError) as ei:
        client.propfind("/x", depth=1)
    assert ei.value.status == 500

def test_book_dav_uses_users_principal_segment(nc):
    assert client.book_dav("contacts") == "/remote.php/dav/addressbooks/users/bot/contacts/"
    assert client.book_dav("my book") == "/remote.php/dav/addressbooks/users/bot/my%20book/"
    with pytest.raises(client.NcError):
        client.book_dav("../x")  # traversal still rejected before any request
    assert not nc.requests


def test_retry_once_on_connect_error(nc, monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, text="ok")

    nc.handler = h
    resp = client.request("GET", "/x")
    assert resp.status_code == 200
    assert calls["n"] == 2


def test_no_retry_on_http_error_status(nc):
    nc.handler = lambda req: httpx.Response(404, text="nf")
    resp = client.request("GET", "/x")
    assert resp.status_code == 404
    assert len(nc.requests) == 1


def test_nc_ocs_traversal_rejected_without_request(nc, call):
    for bad in ("/apps/x", "apps/../secret", "a/../../b", ".."):
        res = call("nc_ocs", {"path": bad})
        assert res["ok"] is False, bad
    assert nc.requests == []  # traversal never becomes a request


def test_nc_ocs_passes_through(nc, call):
    nc.handler = lambda req: ocs_ok([1, 2, 3])
    res = call("nc_ocs", {"method": "GET", "path": "apps/spreed/api/v4/room", "params": {"limit": 5}})
    assert res["ok"] and res["data"] == [1, 2, 3]
    assert nc.requests[0].url.path == "/ocs/v2.php/apps/spreed/api/v4/room"
    assert nc.requests[0].url.params["limit"] == "5"


def test_tool_decorator_never_raises(nc, call):
    # default handler 404s -> NcError -> error JSON, not an exception
    res = call("nc_file_get", {"path": "/missing"})
    assert res["ok"] is False
    assert isinstance(res["error"], str)


def test_secret_prefers_nc_over_talk(monkeypatch):
    monkeypatch.setenv("TALK_SERVER_URL", "https://talk.example")
    monkeypatch.setenv("NC_SERVER_URL", "https://nc.example")
    assert client._secret("TALK_SERVER_URL") == "https://nc.example"
    monkeypatch.delenv("NC_SERVER_URL")
    assert client._secret("TALK_SERVER_URL") == "https://talk.example"
    monkeypatch.setenv("NC_SERVER_URL", "")  # empty NC_* falls through to TALK_*
    assert client._secret("TALK_SERVER_URL") == "https://talk.example"


def test_redaction_strips_both_spellings(nc, monkeypatch):
    monkeypatch.setenv("NC_APP_PASSWORD", "nc-pw")
    assert client.redact("leak nc-pw and s3cret-pw") == "leak *** and ***"
