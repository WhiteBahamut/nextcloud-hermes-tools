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


def test_resp_message_parses_dav_xml_error(nc):
    # sabre-style error body; the s: prefix URI is irrelevant (local-name
    # matching), so an allowlisted namespace stands in for sabredav.org/ns
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:error xmlns:d="DAV:" xmlns:s="https://nextcloud.org/ns">'
        "<s:exception>Sabre\\DAV\\Exception\\NotFound</s:exception>"
        "<s:message>File with name /x not found</s:message>"
        "</d:error>"
    )
    resp = httpx.Response(404, text=body)
    assert client.resp_message(resp) == "Sabre\\DAV\\Exception\\NotFound: File with name /x not found"
    assert len(client.resp_message(resp)) <= 300


def test_resp_message_dav_xml_message_only_and_fallbacks(nc):
    body = '<d:error xmlns:d="DAV:" xmlns:s="https://nextcloud.org/ns"><s:message>nope</s:message></d:error>'
    assert client.resp_message(httpx.Response(500, text=body)) == "nope"
    # OCS JSON meta.message still wins when present
    ocs = httpx.Response(400, json={"ocs": {"meta": {"message": "ocs msg"}}})
    assert client.resp_message(ocs) == "ocs msg"
    # non-XML body falls back to truncated raw text, never raw XML
    assert client.resp_message(httpx.Response(502, text="<html>" + "x" * 400)) == ("<html>" + "x" * 400)[:300]


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

def test_no_retry_on_unsafe_methods_but_safe_still_retries(nc, monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        raise httpx.ConnectError("refused")

    nc.handler = h
    with pytest.raises(httpx.ConnectError):
        client.request("POST", "/x", data={"a": "b"})
    assert calls["n"] == 1  # write not re-sent blindly
    with pytest.raises(httpx.ConnectError):
        client.request("PROPFIND", "/x")
    assert calls["n"] == 3  # safe method retried once (2 attempts)


def test_nc_ocs_passes_through(nc, call):
    nc.handler = lambda req: ocs_ok([1, 2, 3])
    res = call("nc_ocs", {"method": "GET", "path": "apps/spreed/api/v4/room", "params": {"limit": 5}})
    assert res["ok"] and res["data"] == [1, 2, 3]
    assert nc.requests[0].url.path == "/ocs/v2.php/apps/spreed/api/v4/room"
    assert nc.requests[0].url.params["limit"] == "5"


def test_nc_ocs_put_delete_patch_reach_transport(nc, call):
    nc.handler = lambda req: ocs_ok({"done": True})
    for m in ("PUT", "DELETE", "PATCH"):
        res = call("nc_ocs", {"method": m, "path": "apps/x/thing/1", "params": {"a": "b"}, "data": {"k": "v"}})
        assert res["ok"] and res["method"] == m, m
    methods = [r.method for r in nc.requests]
    assert methods == ["PUT", "DELETE", "PATCH"]
    put, dele, patch = nc.requests
    assert "k=v" in put.content.decode() and put.url.params.get("a") is None  # data only on writes
    assert dele.url.params["a"] == "b" and not dele.content  # params only on GET/DELETE
    assert "k=v" in patch.content.decode()


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


def test_dav_put_with_etag_sends_if_match(nc):
    nc.handler = lambda req: httpx.Response(204)
    client.dav_put("/remote.php/dav/files/bot/a.txt", b"x", "text/plain", etag='"abc"')
    req = nc.requests[0]
    assert req.method == "PUT"
    assert req.headers["If-Match"] == '"abc"'
    assert req.headers["Content-Type"] == "text/plain"
    client.dav_put("/remote.php/dav/files/bot/a.txt", b"x", "text/plain")
    assert "If-Match" not in nc.requests[1].headers
