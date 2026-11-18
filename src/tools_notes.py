"""Notes tools — primary ``/index.php/apps/notes/api/v1/notes``, WebDAV fallback.

Decision rule (checked BEFORE any fallback so a half-succeeded POST never
double-creates): if the API response is not 200 with a JSON body, use WebDAV on
the ``Notes/`` folder (title <-> ``<title>.txt``). Fallback writes still do
read-back verification. List responses truncate note content to a 200-char
preview. ``nc_note_delete`` is DESTRUCTIVE-gated.
"""

from __future__ import annotations

from urllib.parse import unquote

from . import client, schemas
from .dav import PROPFIND_ALL, entry_from_response, parse_multistatus

NOTES_API = "/index.php/apps/notes/api/v1/notes"
PREVIEW = 200


def _api(method, path="", params=None, data=None):
    """Call the Notes API. Returns (True, payload) on 200+JSON, else (False, None)."""
    try:
        resp = client.request(method, NOTES_API + path, params=params, data=data)
        if resp.status_code == 200:
            try:
                return True, resp.json()
            except Exception:
                return False, None
    except Exception:
        pass
    return False, None


def _preview(text) -> str:
    text = text or ""
    return text if len(text) <= PREVIEW else text[:PREVIEW] + "…"


def _note_obj(raw: dict, preview=False) -> dict:
    content = raw.get("content")
    return {
        "id": str(raw.get("id", "")),
        "title": raw.get("title", ""),
        "category": raw.get("category", ""),
        **({"content": _preview(content)} if preview and content is not None else
           {"content": content} if content is not None else {}),
    }


# --- WebDAV fallback -------------------------------------------------------------


_NOTE_SUFFIXES = (".md", ".txt")


def _dav_notes_href(title) -> str:
    """Create-path for a DAV-fallback note (legacy .txt convention, kept)."""
    return client.files_dav("Notes/" + title + ".txt")


def _dav_resolve(title):
    """href of existing Notes/<title>.md|.txt via PROPFIND depth 1, else None."""
    base = client.files_dav("Notes")
    prefix = client.files_dav("/").rstrip("/")
    resp = client.propfind(base, depth=1, body=PROPFIND_ALL)
    for r in parse_multistatus(resp.text):
        entry = entry_from_response(r, prefix)
        name = entry["name"]
        if entry["is_dir"] or "." not in name:
            continue
        stem, _, suffix = name.rpartition(".")
        if suffix.lower() in ("md", "txt") and stem == title:
            return client.files_dav("Notes/" + name)
    return None


def _dav_list(category="", limit=50, with_content=False):
    href = client.files_dav("Notes")
    prefix = client.files_dav("/").rstrip("/")
    resp = client.propfind(href, depth=1, body=PROPFIND_ALL)
    target = href.rstrip("/")
    notes = []
    for r in parse_multistatus(resp.text):
        if unquote(r["href"]).rstrip("/") == target:
            continue
        entry = entry_from_response(r, prefix)
        name = entry["name"]
        if entry["is_dir"] or "." not in name:
            continue
        stem, _, suffix = name.rpartition(".")
        if suffix.lower() not in ("md", "txt"):
            continue
        title = stem
        note = {"id": title, "title": title, "category": category, "size": entry["size"]}
        if with_content:
            try:
                note["content"] = _preview(client.dav_get(client.files_dav("Notes/" + name)).text)
            except client.NcError:
                pass
        notes.append(note)
        if len(notes) >= limit:
            break
    return notes


def _dav_get(title):
    last_exc = None
    for suffix in _NOTE_SUFFIXES:
        href = client.files_dav(f"Notes/{title}{suffix}")
        try:
            resp = client.dav_get(href)
            return {"id": title, "title": title, "category": "", "content": resp.text}
        except client.NcError as exc:
            last_exc = exc
    raise last_exc


def _dav_put(title, content, href=None):
    href = href or _dav_notes_href(title)
    data = (content or "").encode("utf-8")
    client.put_verified(href, data, content_type="text/plain; charset=utf-8")


def _dav_delete(title):
    last_exc = None
    for suffix in _NOTE_SUFFIXES:
        href = client.files_dav(f"Notes/{title}{suffix}")
        try:
            client.require(client.dav_delete(href), (200, 204))
        except client.NcError as exc:
            last_exc = exc
            continue
        if client.verify_gone(href):
            return
        raise client.NcError(500, f"delete verification failed: {href} still present")
    raise last_exc


# --- handlers --------------------------------------------------------------------


def _note_list(args):
    category = args.get("category") or ""
    limit = int(args.get("limit") or 50)
    with_content = bool(args.get("with_content"))
    ok_api, payload = _api("GET", params={"category": category} if category else None)
    if ok_api and isinstance(payload, list):
        notes = [_note_obj(n, preview=True) for n in payload if isinstance(n, dict)]
        notes = notes[:limit]
        return client.ok(count=len(notes), notes=notes, via="api")
    notes = _dav_list(category, limit, with_content)
    return client.ok(count=len(notes), notes=notes, via="dav")


def _note_get(args):
    note_id = str(args["id"])
    ok_api, payload = _api("GET", f"/{note_id}")
    if ok_api and isinstance(payload, dict):
        return client.ok(**_note_obj(payload), via="api")
    note = _dav_get(note_id)  # NcError(404) -> error JSON via @tool
    return client.ok(**note, via="dav")


def _note_create(args):
    title = args.get("title") or ""
    if not title:
        return client.err("title required")
    content = args.get("content") or ""
    category = args.get("category") or ""
    ok_api, payload = _api("POST", data={"title": title, "content": content, "category": category})
    if ok_api and isinstance(payload, dict) and payload.get("id") is not None:
        new_id = str(payload["id"])
        ok_check, check = _api("GET", f"/{new_id}")
        if ok_check and isinstance(check, dict) and check.get("title") == title:
            return client.ok(id=new_id, title=title, verified=True, via="api")
        return client.err(f"create verification failed: note {new_id} read-back mismatch", title=title)
    # WebDAV fallback (API not 200-JSON — checked before this point)
    _dav_put(title, content)
    return client.ok(id=title, title=title, verified=True, via="dav")


def _note_edit(args):
    note_id = str(args["id"])
    content = args.get("content")
    title = args.get("title") or ""
    if content is None and not title:
        return client.err("nothing to edit: provide content and/or title")
    data = {}
    if content is not None:
        data["content"] = content
    if title:
        data["title"] = title
    # Notes API v1 has a single update route: PUT /notes/{id} with an attribute
    # body (there is no /notes/{id}/content route).
    ok_api, _payload = _api("PUT", f"/{note_id}", data=data)
    if ok_api:
        ok_check, check = _api("GET", f"/{note_id}")
        if ok_check and isinstance(check, dict) and \
                (content is None or check.get("content") == content) and \
                (not title or check.get("title") == title):
            return client.ok(id=note_id, title=check.get("title") or title, verified=True, via="api")
        return client.err(f"edit verification failed: note {note_id} read-back mismatch", id=note_id)
    # WebDAV fallback: edit the existing .md/.txt file; never create a
    # <numeric-id>.txt sidecar for an API note when the API is unavailable.
    href = _dav_resolve(note_id) or (_dav_resolve(title) if title else None)
    if href is None:
        if note_id.isdigit():
            return client.err(
                f"cannot edit note {note_id}: Notes API unavailable and no Notes/{note_id}.md/.txt file",
                id=note_id)
        href = _dav_notes_href(note_id)  # DAV-mode note: id is the title; create as .txt
    if content is not None:
        _dav_put(note_id, content, href=href)
    if title and title != note_id:
        old = client.dav_get(href).text if content is None else content
        _dav_put(title, old)
        client.require(client.dav_delete(href), (200, 204))
        if not client.verify_gone(href):
            raise client.NcError(500, f"rename verification failed: {href} still present")
    return client.ok(id=title or note_id, title=title or note_id, verified=True, via="dav")


def _note_delete(args):
    note_id = str(args["id"])
    ok_api, _ = _api("DELETE", f"/{note_id}")
    if ok_api:
        ok_check, _payload = _api("GET", f"/{note_id}")
        if not ok_check:
            return client.ok(id=note_id, deleted=True, verified=True, via="api")
        return client.err(f"delete verification failed: note {note_id} still readable", id=note_id)
    _dav_delete(note_id)
    return client.ok(id=note_id, deleted=True, verified=True, via="dav")


TOOLS = [
    ("nc_note_list", schemas.NC_NOTE_LIST, client.tool(_note_list)),
    ("nc_note_get", schemas.NC_NOTE_GET, client.tool(_note_get)),
    ("nc_note_create", schemas.NC_NOTE_CREATE, client.tool(_note_create)),
    ("nc_note_edit", schemas.NC_NOTE_EDIT, client.tool(_note_edit)),
    ("nc_note_delete", schemas.NC_NOTE_DELETE, client.tool(_note_delete)),
]
