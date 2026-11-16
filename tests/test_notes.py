"""Notes handlers: API-first with DAV fallback, read-back verification, list limits."""

import httpx
from conftest import FILES_DAV, NOTES_API, multistatus


# --- notes handlers --------------------------------------------------------------------


def test_notes_api_998_falls_back_to_dav_and_checks_api_first(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if p.startswith("/index.php/apps/notes"):
            return httpx.Response(998, text="OCS path broken")  # not 200 -> DAV fallback
        if req.method == "PUT":
            state[p] = req.content
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, content=state[p]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_note_create", {"title": "Shopping", "content": "milk"})
    assert res["ok"] and res["via"] == "dav" and res["verified"]
    assert state[f"{FILES_DAV}/Notes/Shopping.txt"] == b"milk"
    api_call = next(r for r in nc.requests if r.url.path.startswith("/index.php/apps/notes"))
    put = next(r for r in nc.requests if r.method == "PUT")
    assert nc.requests.index(api_call) < nc.requests.index(put)  # API checked BEFORE fallback write


def test_notes_api_happy_path(nc, call):
    def h(req):
        p = req.url.path
        if p == NOTES_API and req.method == "POST":
            return httpx.Response(200, json={"id": 7, "title": "T", "content": "c", "category": ""})
        if p == f"{NOTES_API}/7":
            return httpx.Response(200, json={"id": 7, "title": "T", "content": "c"})
        return httpx.Response(998, text="x")

    nc.handler = h
    res = call("nc_note_create", {"title": "T", "content": "c"})
    assert res["ok"] and res["via"] == "api" and res["id"] == "7" and res["verified"]
    assert not any(r.method == "PUT" and "/dav/" in r.url.path for r in nc.requests)  # no double-create


def test_note_list_preview_truncated(nc, call):
    long_content = "x" * 500

    def h(req):
        return httpx.Response(200, json=[{"id": 1, "title": "n", "category": "", "content": long_content}])

    nc.handler = h
    res = call("nc_note_list", {})
    assert res["ok"] and res["via"] == "api"
    assert len(res["notes"][0]["content"]) == 201  # 200 chars + ellipsis


def test_note_edit_content_uses_put_notes_id_route(nc, call):
    def h(req):
        p = req.url.path
        if p == f"{NOTES_API}/7" and req.method == "PUT":
            return httpx.Response(200, json={"id": 7, "title": "T", "content": "new body"})
        if p == f"{NOTES_API}/7" and req.method == "GET":
            return httpx.Response(200, json={"id": 7, "title": "T", "content": "new body"})
        return httpx.Response(998, text="x")

    nc.handler = h
    res = call("nc_note_edit", {"id": "7", "content": "new body"})
    assert res["ok"] and res["via"] == "api" and res["verified"] and res["title"] == "T"
    puts = nc.find("PUT", NOTES_API)
    assert len(puts) == 1 and puts[0].url.path == f"{NOTES_API}/7"
    assert not any("/content" in r.url.path for r in nc.requests)  # no nonexistent /content route


def test_note_edit_explicit_empty_content_clears(nc, call):
    # B4 tripwire: explicit content="" must be sent as an empty value (clear the
    # note), not treated as an omitted key
    def h(req):
        p = req.url.path
        if p == f"{NOTES_API}/7" and req.method == "PUT":
            return httpx.Response(200, json={"id": 7, "title": "T", "content": ""})
        if p == f"{NOTES_API}/7" and req.method == "GET":
            return httpx.Response(200, json={"id": 7, "title": "T", "content": ""})
        return httpx.Response(998, text="x")

    nc.handler = h
    res = call("nc_note_edit", {"id": "7", "content": ""})
    assert res["ok"] and res["verified"]
    puts = nc.find("PUT", NOTES_API)
    assert len(puts) == 1 and b"content=" in puts[0].content  # sent as empty form field


def test_note_edit_dav_fallback_numeric_id_creates_no_sidecar(nc, call):
    def h(req):
        p = req.url.path
        if p.startswith("/index.php/apps/notes"):
            return httpx.Response(998, text="api down")
        if req.method == "PROPFIND" and p == f"{FILES_DAV}/Notes":
            return multistatus([(f"{FILES_DAV}/Notes", "")])  # empty Notes folder
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_note_edit", {"id": "195476", "content": "v2"})
    assert res["ok"] is False
    assert not any(r.method == "PUT" and "/Notes/" in r.url.path for r in nc.requests)  # no <id>.txt sidecar


def test_note_edit_dav_fallback_edits_existing_md(nc, call):
    state = {}
    note_href = f"{FILES_DAV}/Notes/My%20note.md"

    def h(req):
        p = req.url.path
        if p.startswith("/index.php/apps/notes"):
            return httpx.Response(998, text="api down")
        if req.method == "PROPFIND" and p == f"{FILES_DAV}/Notes":
            return multistatus([
                (f"{FILES_DAV}/Notes", ""),
                (note_href, "<oc:getcontentlength>3</oc:getcontentlength>"),
            ])
        if req.method == "PUT":
            state[p] = req.content
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, content=state[p]) if p in state else httpx.Response(404, text="nf")
        if req.method == "DELETE":
            state.pop(p, None)
            return httpx.Response(204)
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_note_edit", {"id": "My note", "content": "v2"})
    assert res["ok"] and res["via"] == "dav" and res["verified"]
    assert state[f"{FILES_DAV}/Notes/My note.md"] == b"v2"  # req.url.path is decoded; raw_path keeps %20


def test_note_get_by_title_finds_md(nc, call):
    def h(req):
        p = req.url.path
        if p.startswith("/index.php/apps/notes"):
            return httpx.Response(400, text="bad request")  # API cannot resolve a title id
        if req.method == "GET" and p == f"{FILES_DAV}/Notes/Title.md":
            return httpx.Response(200, content=b"md body")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_note_get", {"id": "Title"})
    assert res["ok"] and res["via"] == "dav" and res["content"] == "md body"


def test_note_edit_api_readback_mismatch_returns_err(nc, call):
    def h(req):
        p = req.url.path
        if p == f"{NOTES_API}/7" and req.method == "PUT":
            return httpx.Response(200, json={"id": 7, "title": "T", "content": "new body"})
        if p == f"{NOTES_API}/7" and req.method == "GET":
            return httpx.Response(200, json={"id": 7, "title": "T", "content": "stale"})  # read-back mismatch
        return httpx.Response(998, text="x")

    nc.handler = h
    res = call("nc_note_edit", {"id": "7", "content": "new body"})
    assert res["ok"] is False and "read-back mismatch" in res["error"]


def _notes_dav_handler(req):
    p = req.url.path
    if p.startswith("/index.php/apps/notes"):
        return httpx.Response(998, text="api down")  # force DAV fallback
    if req.method == "PROPFIND":
        return multistatus([
            (f"{FILES_DAV}/Notes/", '<d:resourcetype><d:collection/></d:resourcetype>'),
            (f"{FILES_DAV}/Notes/a.txt", '<d:resourcetype/><d:getcontentlength>10</d:getcontentlength>'),
            (f"{FILES_DAV}/Notes/b.txt", '<d:resourcetype/><d:getcontentlength>20</d:getcontentlength>'),
            (f"{FILES_DAV}/Notes/c.txt", '<d:resourcetype/><d:getcontentlength>30</d:getcontentlength>'),
        ])
    if req.method == "GET" and "/Notes/" in p:
        return httpx.Response(200, content=b"note body")
    return httpx.Response(404, text="nf")


def test_note_list_dav_default_is_metadata_only_no_per_note_get(nc, call):
    nc.handler = _notes_dav_handler
    res = call("nc_note_list", {})
    assert res["ok"] and res["via"] == "dav" and res["count"] == 3
    assert all("content" not in n for n in res["notes"])
    assert res["notes"][0]["size"] == 10
    assert not any(r.method == "GET" and "/Notes/" in r.url.path for r in nc.requests)


def test_note_list_dav_with_content_fetches_previews(nc, call):
    nc.handler = _notes_dav_handler
    res = call("nc_note_list", {"with_content": True})
    assert res["ok"] and res["count"] == 3
    assert all(n["content"] == "note body" for n in res["notes"])
    assert sum(1 for r in nc.requests if r.method == "GET" and "/Notes/" in r.url.path) == 3


def test_note_list_limit_applies_on_dav_path(nc, call):
    nc.handler = _notes_dav_handler
    res = call("nc_note_list", {"limit": 2})
    assert res["ok"] and res["count"] == 2 and len(res["notes"]) == 2


def test_note_list_limit_applies_on_api_path(nc, call):
    payload = [{"id": i, "title": t, "content": "x"} for i, t in enumerate(["a", "b", "c"], 1)]
    nc.handler = lambda req: (
        httpx.Response(200, json=payload)
        if req.url.path.startswith("/index.php/apps/notes")
        else httpx.Response(404, text="nf")
    )
    res = call("nc_note_list", {"limit": 2})
    assert res["ok"] and res["via"] == "api" and res["count"] == 2
