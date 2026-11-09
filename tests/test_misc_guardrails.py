import httpx
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


def test_guard_hard_block_destructive():
    ctx = FakeCtx({"hard_block_destructive": True})
    client.configure(ctx)
    try:
        d = guardrails.guard("nc_trash_empty", {})
        assert d["action"] == "block" and d["rule_key"] == "nc-destructive"
        assert guardrails.guard("nc_file_put", {"path": "/x"})["action"] == "approve"  # writes unaffected
        assert guardrails.guard("nc_file_list", {}) is None
    finally:
        client.configure(FakeCtx())


def test_guard_never_raises_and_fails_toward_gate():
    class Boom:
        def get(self, _k, _d=None):
            raise RuntimeError("boom")

    res = guardrails.guard("nc_file_put", Boom())
    assert res is not None and res["action"] == "approve"  # internal error -> approve, not raise
    assert guardrails.guard("other_tool", Boom()) is None


def test_guard_brief_truncates_long_paths():
    w = guardrails.guard("nc_file_put", {"path": "/" + "x" * 500})
    assert len(w["message"]) < 300


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
