"""nc_note_list: limit on both paths, DAV content opt-in via with_content (review P3+A2)."""

import httpx

from conftest import multistatus


def _notes_dav_handler(req):
    p = req.url.path
    if p.startswith("/index.php/apps/notes"):
        return httpx.Response(998, text="api down")  # force DAV fallback
    if req.method == "PROPFIND":
        return multistatus([
            ("/remote.php/dav/files/bot/Notes/", '<d:resourcetype><d:collection/></d:resourcetype>'),
            ("/remote.php/dav/files/bot/Notes/a.txt", '<d:resourcetype/><d:getcontentlength>10</d:getcontentlength>'),
            ("/remote.php/dav/files/bot/Notes/b.txt", '<d:resourcetype/><d:getcontentlength>20</d:getcontentlength>'),
            ("/remote.php/dav/files/bot/Notes/c.txt", '<d:resourcetype/><d:getcontentlength>30</d:getcontentlength>'),
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
