import httpx
import json
import pytest
import conftest
from conftest import FakeCtx, multistatus, ocs_ok
from nextcloud_tools import client, guardrails

FILES = "/remote.php/dav/files/bot"
TRASH = "/remote.php/dav/trashbin/bot/trash"


# --- guardrails ------------------------------------------------------------------------


def test_guard_matrix():
    g = guardrails.guard
    assert g("nc_file_list", {"path": "/"}) is None
    assert g("nc_search", {"term": "x"}) is None
    assert g("nc_note_get", {"id": "1"}) is None
    assert g("nc_trash_list", {}) is None
    assert g("terminal", {"cmd": "ls"}) is None  # non-nc passthrough
    assert g("", {}) is None
    w = g("nc_file_put", {"path": "/a.txt"})
    assert w["action"] == "approve" and w["rule_key"] == "nc-write" and "/a.txt" in w["message"]
    assert g("nc_task_reopen", {"uid": "x"})["rule_key"] == "nc-write"
    d = g("nc_file_delete", {"path": "/a.txt"})
    assert d["action"] == "approve" and d["rule_key"] == "nc-destructive"
    assert g("nc_comments", {"action": "list", "file_id": "1"}) is None
    assert g("nc_comments", {"action": "add", "file_id": "1", "message": "m"})["rule_key"] == "nc-write"
    assert g("nc_comments", {"action": "delete", "file_id": "1", "comment_id": 2})["rule_key"] == "nc-destructive"
    assert g("nc_ocs", {"method": "GET", "path": "x"}) is None
    assert g("nc_ocs", {"method": "POST", "path": "x"})["action"] == "approve"
    d2 = g("nc_cal_delete", {"calendar": "personal", "uid": "8f6cf60a-x"})
    assert d2["rule_key"] == "nc-destructive"
    assert d2["message"] == "Destructive Nextcloud op — delete event with uid '8f6cf60a-x' in calendar 'personal' (nc_cal_delete)"
    c = g("nc_cal_create", {"summary": "Standup", "start": "2026-11-16T09:00:00Z", "end": "2026-11-16T09:30:00Z"})
    assert "create event 'Standup' in calendar 'personal'" in c["message"]  # schema default applied


def test_guard_hard_block_destructive():
    ctx = FakeCtx({"hard_block_destructive": True})
    client.configure(ctx)
    try:
        d = guardrails.guard("nc_trash_empty", {})
        assert d["action"] == "block" and d["rule_key"] == "nc-destructive"
        assert d["message"].startswith("Destructive Nextcloud op hard-blocked (hard_block_destructive) — ")
        assert "empty the ENTIRE trashbin (nc_trash_empty)" in d["message"]
        assert guardrails.guard("nc_file_put", {"path": "/x"})["action"] == "approve"  # writes unaffected
        assert guardrails.guard("nc_file_list", {}) is None
    finally:
        client.configure(FakeCtx())


def test_guard_ungated_write_tool_returns_none():
    client.configure(FakeCtx({"ungated_tools": ["nc_file_put"]}))
    try:
        assert guardrails.guard("nc_file_put", {"path": "/a"}) is None
        # other writes still gated
        assert guardrails.guard("nc_file_mkdir", {"path": "/b"})["action"] == "approve"
    finally:
        client.configure(FakeCtx())


def test_guard_ungated_destructive_tool_returns_none():
    client.configure(FakeCtx({"ungated_tools": ["nc_file_delete"]}))
    try:
        assert guardrails.guard("nc_file_delete", {"path": "/x"}) is None
    finally:
        client.configure(FakeCtx())


def test_guard_hard_block_wins_over_ungated_destructive():
    client.configure(FakeCtx({"ungated_tools": ["nc_file_delete"], "hard_block_destructive": True}))
    try:
        d = guardrails.guard("nc_file_delete", {"path": "/x"})
        assert d["action"] == "block" and d["rule_key"] == "nc-destructive"
    finally:
        client.configure(FakeCtx())


def test_guard_ungated_read_tool_returns_none():
    client.configure(FakeCtx({"ungated_tools": ["nc_file_list"]}))
    try:
        assert guardrails.guard("nc_file_list", {}) is None
    finally:
        client.configure(FakeCtx())


def test_guard_ungated_arg_dispatched_tool_covers_all_actions():
    client.configure(FakeCtx({"ungated_tools": ["nc_ocs"]}))
    try:
        assert guardrails.guard("nc_ocs", {"method": "DELETE", "path": "x"}) is None
        assert guardrails.guard("nc_ocs", {"method": "POST", "path": "x"}) is None
    finally:
        client.configure(FakeCtx())


def test_guard_wrong_typed_ungated_tools_fails_toward_gate():
    client.configure(FakeCtx({"ungated_tools": "nc_file_put"}))
    try:
        assert guardrails.guard("nc_file_put", {"path": "/a"})["action"] == "approve"
    finally:
        client.configure(FakeCtx())


def test_guard_never_raises_and_fails_toward_gate():
    class Boom:
        def get(self, _k, _d=None):
            raise RuntimeError("boom")

    res = guardrails.guard("nc_file_put", Boom())
    assert res is not None and res["action"] == "approve" and res["rule_key"] == "nc-error"  # never raises
    assert guardrails.guard("other_tool", Boom()) is None


def test_guard_brief_truncates_long_paths():
    w = guardrails.guard("nc_file_put", {"path": "/" + "x" * 500})
    assert len(w["message"]) < 300
    assert "…" in w["message"]  # interpolated values truncate at 120 chars
    assert "x" * 120 not in w["message"]


def test_guard_file_put_summary_shows_byte_size():
    g = guardrails.guard
    w = g("nc_file_put", {"path": "/a.txt", "content": "hello"})
    assert "create or overwrite file '/a.txt' (5 bytes) (nc_file_put)" in w["message"]
    w = g("nc_file_put", {"path": "/a.bin", "content_base64": "AAECAwQ="})
    assert "(5 bytes)" in w["message"]
    w = g("nc_file_put", {"path": "/a.txt", "allow_empty": True})
    assert "(0 bytes, empty file)" in w["message"]


@pytest.mark.parametrize("name", sorted(guardrails.WRITES | guardrails.DESTRUCTIVE))
def test_guard_summary_covers_every_gated_tool(name):
    assert name in guardrails._SUMMARIES
    args = {"path": "/p", "source": "/s", "destination": "/d", "token": "t", "trash_path": "/tr",
            "uid": "u", "id": "7", "share_with": "bob", "share_type": 0, "permissions": 1,
            "message": "m", "message_id": 3, "emoji": "👍", "calendar": "cal", "summary": "s",
            "start": "st", "end": "en", "book": "b", "fn": "f", "title": "ti", "tag": "tg"}
    res = guardrails.guard(name, args)
    prefix = "Destructive Nextcloud op — " if name in guardrails.DESTRUCTIVE else "Nextcloud write — "
    assert res["action"] == "approve"
    assert res["message"].startswith(prefix) and res["message"].endswith(f"({name})")


def test_guard_summary_arg_dispatch():
    g = guardrails.guard
    add = g("nc_comments", {"action": "add", "file_id": "1", "message": "m"})
    assert add["rule_key"] == "nc-write" and "add comment 'm' on file 1 (nc_comments)" in add["message"]
    add_path = g("nc_comments", {"action": "add", "path": "/Docs/a.txt", "message": "m"})
    assert "on file /Docs/a.txt" in add_path["message"]  # path used when file_id absent
    dele = g("nc_comments", {"action": "delete", "file_id": "1", "comment_id": 2})
    assert dele["rule_key"] == "nc-destructive"
    assert "delete comment id 2 on file 1 (nc_comments)" in dele["message"]
    post = g("nc_ocs", {"method": "POST", "path": "x"})
    assert "POST /ocs/v2.php/x (nc_ocs)" in post["message"]
    react = g("nc_talk_react", {"token": "t", "message_id": 5, "emoji": "👍", "react": False})
    assert "remove reaction '👍' on message id 5 in room t (nc_talk_react)" in react["message"]


def test_guard_readable_targets_from_args():
    g = guardrails.guard
    d = g("nc_note_delete", {"id": "195531"})
    assert d["message"] == "Destructive Nextcloud op — delete note with id '195531' (nc_note_delete)"
    e = g("nc_note_edit", {"id": "195531", "title": "Shopping list"})
    assert "edit note 'Shopping list' (id 195531)" in e["message"]
    e2 = g("nc_note_edit", {"id": "195531"})
    assert "edit note with id '195531'" in e2["message"]
    c = g("nc_contact_edit", {"uid": "u1", "fn": "Alice"})
    assert "edit contact 'Alice' (uid u1) in address book 'contacts'" in c["message"]
    c2 = g("nc_contact_edit", {"uid": "u1"})
    assert "edit contact with uid 'u1' in address book 'contacts'" in c2["message"]


def test_guard_makes_zero_network_requests(nc):
    args = {"path": "/p", "source": "/s", "destination": "/d", "token": "t", "trash_path": "/tr",
            "uid": "u", "id": "7", "share_with": "bob", "share_type": 0, "permissions": 1,
            "message": "m", "message_id": 3, "emoji": "👍", "calendar": "cal", "summary": "s",
            "start": "st", "end": "en", "book": "b", "fn": "f", "title": "ti", "tag": "tg"}
    for name in sorted(guardrails.WRITES | guardrails.DESTRUCTIVE):
        guardrails.guard(name, args)
    guardrails.guard("nc_comments", {"action": "add", "file_id": "1", "message": "m"})
    guardrails.guard("nc_comments", {"action": "delete", "file_id": "1", "comment_id": 2})
    guardrails.guard("nc_ocs", {"method": "POST", "path": "x"})
    assert nc.requests == []


def test_guard_message_redacts_secrets(monkeypatch):
    monkeypatch.setenv("TALK_APP_PASSWORD", "SECRET123")
    w = guardrails.guard("nc_talk_send", {"token": "t", "message": "pw is SECRET123"})
    assert w["action"] == "approve"
    assert "SECRET123" not in w["message"]
    assert "***" in w["message"]


# --- misc handlers -----------------------------------------------------------------------


def test_tag_assign_proppatch_then_readback(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPPATCH":
            body = req.content.decode()
            assert "<oc:systemtag>urgent</oc:systemtag>" in body and "<d:set>" in body
            return multistatus([(p, "<d:set/>")])
        if req.method == "PROPFIND":
            return multistatus([(p, "<oc:systemtags><oc:systemtag>urgent</oc:systemtag></oc:systemtags>")])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_tag_assign", {"path": "/a.txt", "tag": "urgent"})
    assert res["ok"] and res["verified"] is True
    assert nc.methods() == ["PROPPATCH", "PROPFIND"]


def test_tag_unassign_uses_remove(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPPATCH":
            assert "<d:remove>" in req.content.decode()
            return multistatus([(p, "<d:remove/>")])
        if req.method == "PROPFIND":
            return multistatus([(p, "<oc:systemtags/>")])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_tag_unassign", {"path": "/a.txt", "tag": "urgent"})
    assert res["ok"] and res["verified"]


def test_trash_restore_moves_with_overwrite_f(nc, call):
    restored = {}

    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p.startswith(TRASH):
            return multistatus([(p, "<oc:trashbin-original-location>/Docs/</oc:trashbin-original-location>"
                                   "<oc:trashbin-original-filename>a.txt</oc:trashbin-original-filename>")])
        if req.method == "MOVE":
            assert req.headers["Overwrite"] == "F"
            restored["dest"] = req.headers["Destination"]
            return httpx.Response(201)
        if req.method == "PROPFIND":
            dest_path = restored["dest"].replace("https://nc.example", "")
            if p.rstrip("/") == dest_path.rstrip("/"):
                return multistatus([(p, "<d:resourcetype/>")])
            return httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_trash_restore", {"trash_path": "/Docs/a.txt.d123"})
    assert res["ok"] and res["restored_to"] == "/Docs/a.txt" and res["verified"]
    assert restored["dest"] == f"https://nc.example{FILES}/Docs/a.txt"


def test_comments_resolves_path_to_fileid(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p.startswith(FILES):
            return multistatus([(p, "<oc:fileid>4242</oc:fileid>")])
        if p.startswith("/remote.php/dav/comments/files/4242"):
            return multistatus([
                ("/remote.php/dav/comments/files/4242", ""),
                ("/remote.php/dav/comments/files/4242/1",
                 "<oc:id>1</oc:id><oc:message>hi there</oc:message><oc:actorDisplayName>bot</oc:actorDisplayName>"),
            ])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_comments", {"action": "list", "path": "/a.txt"})
    assert res["ok"] and res["file_id"] == "4242"
    assert res["comments"][0]["message"] == "hi there" and res["comments"][0]["actor"] == "bot"


def test_comments_propfind_requests_oc_props(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p.startswith("/remote.php/dav/comments/files/4242"):
            return multistatus([
                ("/remote.php/dav/comments/files/4242", ""),
                ("/remote.php/dav/comments/files/4242/1",
                 "<oc:id>1</oc:id><oc:message>hi</oc:message><oc:actorDisplayName>bot</oc:actorDisplayName>"),
            ])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_comments", {"action": "list", "file_id": "4242"})
    assert res["ok"]
    assert res["comments"][0]["message"] == "hi"
    assert res["comments"][0]["actor"] == "bot"
    bodies = [r.content for r in nc.requests
              if r.method == "PROPFIND"
              and r.url.path.startswith("/remote.php/dav/comments/files/4242")]
    assert bodies
    for tag in (b"<oc:id/>", b"<oc:message/>", b"<oc:actorId/>", b"<oc:actorDisplayName/>",
                b"<oc:verb/>", b"<oc:creationDateTime/>"):
        assert tag in bodies[0]


def test_comments_add_posts_json_and_verifies(nc, call):
    posted = {}

    def h(req):
        p = req.url.path
        if req.method == "POST" and p == "/remote.php/dav/comments/files/4242/":
            posted["content_type"] = req.headers["Content-Type"]
            posted["body"] = req.content
            return httpx.Response(
                201,
                headers={"Content-Location": "https://nc.example/remote.php/dav/comments/files/4242/10207"},
            )
        if req.method == "PROPFIND" and p.startswith("/remote.php/dav/comments/files/4242"):
            return multistatus([
                ("/remote.php/dav/comments/files/4242", ""),
                ("/remote.php/dav/comments/files/4242/10207",
                 "<oc:id>10207</oc:id><oc:message>hello</oc:message>"),
            ])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_comments", {"action": "add", "file_id": "4242", "message": "hello"})
    assert res["ok"] and res["added"] and res["verified"] and res["comment_id"] == "10207"
    assert posted["content_type"].startswith("application/json")
    assert json.loads(posted["body"]) == {"actorType": "users", "message": "hello", "verb": "comment"}
    assert all(b"propertyupdate" not in r.content for r in nc.requests)


def test_comments_add_server_error_returns_err_json(nc, call):
    def h(req):
        if req.method == "POST" and "/comments/files/4242" in req.url.path:
            return httpx.Response(415, text="Unsupported Media Type")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_comments", {"action": "add", "file_id": "4242", "message": "hello"})
    assert res["ok"] is False and "415" in res["error"]


def test_comments_add_readback_mismatch_returns_err(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "POST" and p == "/remote.php/dav/comments/files/4242/":
            return httpx.Response(
                201,
                headers={"Content-Location": "https://nc.example/remote.php/dav/comments/files/4242/10207"},
            )
        if req.method == "PROPFIND" and p.startswith("/remote.php/dav/comments/files/4242"):
            return multistatus([
                ("/remote.php/dav/comments/files/4242", ""),
                ("/remote.php/dav/comments/files/4242/10207",
                 "<oc:id>10207</oc:id><oc:message>something else</oc:message>"),
            ])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_comments", {"action": "add", "file_id": "4242", "message": "hello"})
    assert res["ok"] is False and "verification failed" in res["error"]


def test_activity_and_notifications(nc, call):
    def h(req):
        if "/activity/" in req.url.path:
            return httpx.Response(200, json={"ocs": {"meta": {"statuscode": 200}, "data": [{"a": 1}, {"a": 2}]}})
        return ocs_ok([{"notification_id": 5}])

    nc.handler = h
    res = call("nc_activity", {"limit": 10, "since": 123})
    assert res["ok"] and res["count"] == 2
    assert nc.requests[0].url.params["since"] == "123"
    res = call("nc_notifications", {"limit": 5})
    assert res["ok"] and res["notifications"] == [{"notification_id": 5}]
