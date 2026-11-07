"""Misc tools — activity, notifications, systemtags, trashbin, comments, generic OCS.

- Comments DAV needs a numeric fileId — when only ``path`` is given it is
  resolved via PROPFIND ``oc:fileid``.
- Trash restore = MOVE from the trash href to ``Destination`` = original
  location with ``Overwrite: F``.
- ``nc_ocs`` rejects leading ``/`` and any ``..`` segment BEFORE any request.
- Tag assign/unassign verify via PROPFIND read-back.
"""

from __future__ import annotations

from urllib.parse import unquote
from xml.sax.saxutils import escape as xml_escape

from . import client, schemas
from .dav import PROPFIND_ALL, parse_multistatus, user_path


def _dav_base() -> str:
    """'/remote.php/dav' (derived from the files root, no private access)."""
    return client.files_dav("/").split("/files/")[0]


def _user() -> str:
    """URL-quoted bot user name."""
    return client.files_dav("/").split("/files/")[1].rstrip("/")


# --- activity / notifications ------------------------------------------------------


def _activity(args):
    limit = int(args.get("limit") or 50)
    since = int(args.get("since") or 0)
    params = {"format": "json", "limit": limit}
    if since:
        params["since"] = since
    resp = client.require(
        client.request("GET", "/index.php/apps/activity/api/v2/activity", params=params), (200,)
    )
    try:
        payload = resp.json()
    except Exception:
        raise client.NcError(resp.status_code, (resp.text or "")[:300])
    entries = payload.get("ocs", {}).get("data") if isinstance(payload, dict) else payload
    if isinstance(entries, dict):
        entries = entries.get("data", [])
    entries = entries or []
    return client.ok(count=len(entries), activities=entries)


def _notifications(args):
    limit = int(args.get("limit") or 50)
    data = client.ocs("GET", "apps/notifications/api/v2/notifications", params={"limit": limit})
    items = data if isinstance(data, list) else []
    return client.ok(count=len(items), notifications=items)


# --- system tags ---------------------------------------------------------------------


def _tag_list(args):
    resp = client.propfind(f"{_dav_base()}/systemtags/", depth=1, body=PROPFIND_ALL)
    tags = []
    for r in parse_multistatus(resp.text):
        p = r["props"]
        name = p.get("displayname") or p.get("display-name") or p.get("name") or ""
        if not name:
            continue
        tags.append({"id": p.get("id", ""), "name": name})
    return client.ok(count=len(tags), tags=tags)


def _tag_set(args, assign: bool):
    path = args["path"]
    tag = str(args["tag"])
    href = client.files_dav(path)
    verb = "set" if assign else "remove"
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:propertyupdate xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
        f"<d:{verb}><d:prop><oc:systemtags>"
        f"<oc:systemtag>{xml_escape(tag)}</oc:systemtag>"
        f"</oc:systemtags></d:prop></d:{verb}></d:propertyupdate>"
    )
    client.dav_proppatch(href, body)
    resp = client.propfind(href, depth=0, body=PROPFIND_ALL)
    rs = parse_multistatus(resp.text)
    tags = (rs[0]["props"].get("systemtags") or []) if rs else []
    if assign and tag not in tags:
        return client.err(f"tag assign verification failed: {tag!r} not in {tags}", path=path)
    if not assign and tag in tags:
        return client.err(f"tag unassign verification failed: {tag!r} still in {tags}", path=path)
    return client.ok(path=path, tag=tag, assigned=assign, verified=True)


def _tag_assign(args):
    return _tag_set(args, True)


def _tag_unassign(args):
    return _tag_set(args, False)


# --- trashbin ------------------------------------------------------------------------


def _trash_base() -> str:
    return f"{_dav_base()}/trashbin/{_user()}/trash/"


def _trash_list(args):
    limit = int(args.get("limit") or 100)
    base = _trash_base()
    prefix = base.rstrip("/")
    resp = client.propfind(base, depth=1, body=PROPFIND_ALL)
    out = []
    for r in parse_multistatus(resp.text):
        rhref = unquote(r["href"]).rstrip("/")
        if rhref == prefix:
            continue
        p = r["props"]
        size = p.get("getcontentlength") or "0"
        out.append({
            "trash_path": user_path(r["href"], prefix),
            "original_path": (p.get("trashbin-original-location") or "") + (p.get("trashbin-original-filename") or ""),
            "deleted_at": p.get("trashbin-deletion-time"),
            "size": int(size) if str(size).isdigit() else 0,
        })
        if len(out) >= limit:
            break
    return client.ok(count=len(out), entries=out)


def _trash_restore(args):
    trash_path = args["trash_path"]
    base = _trash_base()
    src_href = base + client.enc_path(trash_path).lstrip("/")
    rs = parse_multistatus(client.propfind(src_href, depth=0, body=PROPFIND_ALL).text)
    props = rs[0]["props"] if rs else {}
    orig = (props.get("trashbin-original-location") or "") + (props.get("trashbin-original-filename") or "")
    if not orig:
        return client.err(f"no original location recorded for {trash_path}", trash_path=trash_path)
    dst_href = client.files_dav(orig)
    resp = client.dav_move(src_href, client.abs_url(dst_href), overwrite=False)  # Overwrite: F
    if resp.status_code not in (200, 201, 204):
        raise client.NcError(resp.status_code, client.resp_message(resp))
    if not client.verify_exists(dst_href):
        return client.err(f"restore verification failed: {orig} missing", trash_path=trash_path)
    return client.ok(trash_path=trash_path, restored_to=orig, verified=True)


def _trash_empty(args):
    base = _trash_base()
    client.require(client.dav_delete(base, headers={"Depth": "infinity"}), (200, 204))
    resp = client.propfind(base, depth=1, body=PROPFIND_ALL)
    remaining = [
        r for r in parse_multistatus(resp.text)
        if unquote(r["href"]).rstrip("/") != base.rstrip("/")
    ]
    if remaining:
        return client.err(f"trash empty verification failed: {len(remaining)} entries remain")
    return client.ok(emptied=True, verified=True)


# --- comments ------------------------------------------------------------------------


def _resolve_file_id(args) -> str:
    file_id = str(args.get("file_id") or "")
    if file_id:
        return file_id
    path = args.get("path") or ""
    if not path:
        raise client.NcError(400, "give file_id or path")
    rs = parse_multistatus(client.propfind(client.files_dav(path), depth=0, body=PROPFIND_ALL).text)
    file_id = (rs[0]["props"].get("fileid") or "") if rs else ""
    if not file_id:
        raise client.NcError(404, f"could not resolve oc:fileid for {path}")
    return file_id


def _comment_dict(props: dict) -> dict:
    p = {k.lower(): v for k, v in props.items()}
    return {
        "id": p.get("id") or p.get("commentid") or "",
        "message": p.get("message", ""),
        "actor": p.get("actordisplayname") or p.get("actorid", ""),
        "verb": p.get("verb", ""),
        "created": p.get("creationdatetime", ""),
    }


def _comments_list(base: str, file_id: str):
    resp = client.propfind(base + "/", depth=1, body=PROPFIND_ALL)
    target = base.rstrip("/")
    out = []
    for r in parse_multistatus(resp.text):
        if unquote(r["href"]).rstrip("/") == target:
            continue
        out.append(_comment_dict(r["props"]))
    return out


def _comments(args):
    action = str(args.get("action") or "list")
    file_id = _resolve_file_id(args)
    base = f"{_dav_base()}/comments/files/{file_id}"
    if action == "list":
        comments = _comments_list(base, file_id)
        return client.ok(file_id=file_id, count=len(comments), comments=comments)
    if action == "add":
        message = args.get("message") or ""
        if not message:
            return client.err("message required")
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propertyupdate xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
            "<d:set><d:prop>"
            f"<oc:message>{xml_escape(message)}</oc:message>"
            "</d:prop></d:set></d:propertyupdate>"
        )
        client.require(
            client.request("POST", base + "/", content=body.encode("utf-8"),
                           headers={"Content-Type": "application/xml; charset=utf-8"}),
            (200, 201, 204),
        )
        msgs = [c["message"] for c in _comments_list(base, file_id)]
        if message not in msgs:
            return client.err("add verification failed: message not in read-back", file_id=file_id)
        return client.ok(file_id=file_id, added=True, verified=True)
    if action == "delete":
        cid = int(args.get("comment_id") or 0)
        if not cid:
            return client.err("comment_id required")
        client.require(client.dav_delete(f"{base}/{cid}"), (200, 204))
        ids = [str(c["id"]) for c in _comments_list(base, file_id) if c["id"]]
        if str(cid) in ids:
            return client.err(f"delete verification failed: comment {cid} still present", file_id=file_id)
        return client.ok(file_id=file_id, comment_id=cid, deleted=True, verified=True)
    return client.err(f"unknown action {action!r}")


# --- generic OCS escape hatch ----------------------------------------------------------


def _ocs(args):
    method = str(args.get("method") or "GET").upper()
    path = str(args.get("path") or "")
    if path.startswith("/") or any(seg == ".." for seg in path.split("/")):
        return client.err(f"traversal rejected: {path!r}")  # never a request
    if method not in ("GET", "POST"):
        return client.err(f"method must be GET or POST, got {method!r}")
    data = client.ocs(method, path, params=args.get("params") or None, data=args.get("data") or None)
    return client.ok(method=method, path=path, data=data)


TOOLS = [
    ("nc_activity", schemas.NC_ACTIVITY, client.tool(_activity)),
    ("nc_notifications", schemas.NC_NOTIFICATIONS, client.tool(_notifications)),
    ("nc_tag_list", schemas.NC_TAG_LIST, client.tool(_tag_list)),
    ("nc_tag_assign", schemas.NC_TAG_ASSIGN, client.tool(_tag_assign)),
    ("nc_tag_unassign", schemas.NC_TAG_UNASSIGN, client.tool(_tag_unassign)),
    ("nc_trash_list", schemas.NC_TRASH_LIST, client.tool(_trash_list)),
    ("nc_trash_restore", schemas.NC_TRASH_RESTORE, client.tool(_trash_restore)),
    ("nc_trash_empty", schemas.NC_TRASH_EMPTY, client.tool(_trash_empty)),
    ("nc_comments", schemas.NC_COMMENTS, client.tool(_comments)),
    ("nc_ocs", schemas.NC_OCS, client.tool(_ocs)),
]
