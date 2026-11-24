"""pre_tool_call guardrail: gating matrix, hard-block, ungated fail-safe, redaction."""

import pytest
from conftest import FakeCtx
from nextcloud_tools import client, guardrails


# --- guardrails ------------------------------------------------------------------------


def test_guard_matrix():
    g = guardrails.guard
    assert g("nc_file_list", {"path": "/"}) is None
    assert g("nc_search", {"term": "x"}) is None
    assert g("nc_note_get", {"id": "1"}) is None
    assert g("nc_trash_list", {}) is None
    assert g("nc_version", {}) is None
    assert g("terminal", {"cmd": "ls"}) is None  # non-nc passthrough
    assert g("", {}) is None
    w = g("nc_file_put", {"path": "/a.txt"})
    assert w["action"] == "approve" and w["rule_key"] == "nc-write" and "/a.txt" in w["message"]
    assert g("nc_task_reopen", {"uid": "x"})["rule_key"] == "nc-write"
    d = g("nc_file_delete", {"path": "/a.txt"})
    assert d["action"] == "approve" and d["rule_key"] == "nc-destructive"
    assert g("nc_comment_list", {"file_id": "1"}) is None
    assert g("nc_comment_add", {"file_id": "1", "message": "m"})["rule_key"] == "nc-write"
    assert g("nc_comment_delete", {"file_id": "1", "comment_id": 2})["rule_key"] == "nc-destructive"
    assert g("nc_ocs", {"method": "GET", "path": "x"}) is None
    assert g("nc_ocs", {"method": "POST", "path": "x"})["action"] == "approve"
    d2 = g("nc_cal_delete", {"calendar": "personal", "uid": "8f6cf60a-x"})
    assert d2["rule_key"] == "nc-destructive"
    assert d2["message"] == "Destructive Nextcloud op — delete event with uid '8f6cf60a-x' in calendar 'personal' (nc_cal_delete)"
    c = g("nc_cal_create", {"summary": "Standup", "start": "2026-11-16T09:00:00Z", "end": "2026-11-16T09:30:00Z"})
    assert "create event 'Standup' in calendar 'personal'" in c["message"]  # schema default applied


def test_guard_file_unlock_is_a_gated_write():
    w = guardrails.guard("nc_file_unlock", {"path": "/a.txt"})
    assert w["action"] == "approve" and w["rule_key"] == "nc-write"
    assert "force-unlock file '/a.txt'" in w["message"]
    assert w["message"].endswith("(nc_file_unlock)")
    w2 = guardrails.guard("nc_file_unlock", {"path": "/a.txt", "file_id": "42"})
    assert "42" in w2["message"]


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


def test_guard_ungated_nc_ocs_per_method_entry():
    client.configure(FakeCtx({"ungated_tools": ["nc_ocs:GET"]}))
    try:
        assert guardrails.guard("nc_ocs", {"method": "GET", "path": "x"}) is None
        assert guardrails.guard("nc_ocs", {"path": "x"}) is None  # omitted method = GET
        # other methods stay gated
        assert guardrails.guard("nc_ocs", {"method": "POST", "path": "x"})["action"] == "approve"
        d = guardrails.guard("nc_ocs", {"method": "DELETE", "path": "x"})
        assert d["action"] == "approve" and d["rule_key"] == "nc-destructive"
        # the per-method entry does not ungate anything else
        assert guardrails.guard("nc_file_put", {"path": "/a"})["action"] == "approve"
    finally:
        client.configure(FakeCtx())


def test_guard_hard_block_wins_over_nc_ocs_per_method_ungate():
    client.configure(FakeCtx({"ungated_tools": ["nc_ocs:DELETE"], "hard_block_destructive": True}))
    try:
        d = guardrails.guard("nc_ocs", {"method": "DELETE", "path": "x"})
        assert d["action"] == "block" and d["rule_key"] == "nc-destructive"
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
    add = g("nc_comment_add", {"file_id": "1", "message": "m"})
    assert add["rule_key"] == "nc-write" and "add comment 'm' on file 1 (nc_comment_add)" in add["message"]
    add_path = g("nc_comment_add", {"path": "/Docs/a.txt", "message": "m"})
    assert "on file /Docs/a.txt" in add_path["message"]  # path used when file_id absent
    dele = g("nc_comment_delete", {"file_id": "1", "comment_id": 2})
    assert dele["rule_key"] == "nc-destructive"
    assert "delete comment id 2 on file 1 (nc_comment_delete)" in dele["message"]
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
    guardrails.guard("nc_comment_add", {"file_id": "1", "message": "m"})
    guardrails.guard("nc_comment_delete", {"file_id": "1", "comment_id": 2})
    guardrails.guard("nc_ocs", {"method": "POST", "path": "x"})
    assert nc.requests == []


def test_guard_message_redacts_secrets(monkeypatch):
    monkeypatch.setenv("TALK_APP_PASSWORD", "SECRET123")
    w = guardrails.guard("nc_talk_send", {"token": "t", "message": "pw is SECRET123"})
    assert w["action"] == "approve"
    assert "SECRET123" not in w["message"]
    assert "***" in w["message"]


def test_guard_nc_ocs_method_gating(fake_ctx):
    from nextcloud_tools import guardrails

    assert guardrails.guard("nc_ocs", {"method": "GET", "path": "x"}) is None
    assert guardrails.guard("nc_ocs", {"path": "x"}) is None  # default GET
    for m in ("POST", "PUT", "patch"):
        w = guardrails.guard("nc_ocs", {"method": m, "path": "x"})
        assert w["action"] == "approve" and w["rule_key"] == "nc-write", m
    d = guardrails.guard("nc_ocs", {"method": "DELETE", "path": "x"})
    assert d["action"] == "approve" and d["rule_key"] == "nc-destructive"
    assert "DELETE /ocs/v2.php/x (destructive)" in d["message"]
