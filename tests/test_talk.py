from urllib.parse import unquote

import conftest
from conftest import ocs_ok


def test_chat_request_has_lookintofuture_zero(nc, call):
    nc.handler = lambda req: ocs_ok([{"id": 1, "message": "hi"}])
    res = call("nc_talk_messages", {"token": "tok1", "limit": 10, "last_known_message_id": 5})
    assert res["ok"] and res["count"] == 1
    req = nc.requests[0]
    assert "/room/tok1/chat" in req.url.path
    assert req.url.params["lookIntoFuture"] == "0"  # never poll
    assert req.url.params["limit"] == "10"
    assert req.url.params["lastKnownMessageId"] == "5"


def test_rooms_filter_dms_and_skip_tokens(nc):
    _ctx, call = conftest.make_caller({"talk_skip_tokens": ["dm-token"], "talk_include_dms": False})
    nc.handler = lambda req: ocs_ok([
        {"token": "room1", "roomType": 2, "name": "General"},
        {"token": "dm-token", "roomType": 1, "name": "gateway DM"},
        {"token": "dm2", "roomType": 1, "name": "other DM"},
    ])
    res = call("nc_talk_rooms", {})
    assert res["ok"]
    assert [r["token"] for r in res["rooms"]] == ["room1"]


def test_rooms_include_dms_only_when_setting_on(nc):
    _ctx, call = conftest.make_caller({"talk_include_dms": True, "talk_skip_tokens": ["dm-token"]})
    nc.handler = lambda req: ocs_ok([
        {"token": "dm-token", "roomType": 1},
        {"token": "dm2", "roomType": 1},
        {"token": "r", "roomType": 2},
    ])
    res = call("nc_talk_rooms", {})
    assert sorted(r["token"] for r in res["rooms"]) == ["dm2", "r"]  # skip-token still dropped


def test_send_verified_by_chat_readback(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "POST" and p.endswith("/chat"):
            return ocs_ok({"id": 42})
        if req.method == "GET" and p.endswith("/chat"):
            return ocs_ok([{"id": 42, "message": "hi"}])
        return ocs_ok([])

    nc.handler = h
    res = call("nc_talk_send", {"token": "t", "message": "hi", "reply_to": 7})
    assert res["ok"] and res["message_id"] == 42 and res["verified"] is True
    post = nc.find("POST", "/chat")[0]
    assert b"message=hi" in post.content and b"replyTo=7" in post.content  # form field


def test_send_readback_missing_fails(nc, call):
    nc.handler = lambda req: ocs_ok({"id": 42}) if req.method == "POST" else ocs_ok([{"id": 1}])
    res = call("nc_talk_send", {"token": "t", "message": "hi"})
    assert res["ok"] is False


def test_react_url_quotes_emoji(nc, call):
    nc.handler = lambda req: ocs_ok([])
    res = call("nc_talk_react", {"token": "t", "message_id": 7, "emoji": "👍"})
    assert res["ok"] and res["verified"]
    # emoji is URL-quoted in the path (round-trips through unquote)
    assert any("/reaction/" in r.url.path and "👍" in unquote(r.url.path) for r in nc.requests)
    assert nc.methods() == ["POST"]
    res = call("nc_talk_react", {"token": "t", "message_id": 7, "emoji": "👍", "react": False})
    assert res["ok"]
    assert nc.methods()[-1] == "DELETE"


def test_talk_delete_verified(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "DELETE":
            return ocs_ok([])
        return ocs_ok([{"id": 1}])  # 9 gone from read-back

    nc.handler = h
    res = call("nc_talk_delete", {"token": "t", "message_id": 9})
    assert res["ok"] and res["deleted"] and res["verified"]
