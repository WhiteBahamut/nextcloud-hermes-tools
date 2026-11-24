"""Misc tools — activity, notifications, systemtags, trashbin, comments, generic OCS.

- Comments DAV needs a numeric fileId — when only ``path`` is given it is
  resolved via PROPFIND ``oc:fileid``.
- Trash restore = MOVE from the trash href to ``Destination`` = original
  location with ``Overwrite: F``.
- ``nc_ocs`` rejects leading ``/`` and any ``..`` segment BEFORE any request.
- Tag assign/unassign verify via PROPFIND read-back.
- ``nc_file_unlock``: DELETE /ocs/v2.php/apps/files_lock/lock/<fileId> as file owner (OCS-APIRequest header is set client-wide in client.get_client); lock state via a local PROPFIND <nc:lock/> body; folders rejected at resolution.
- ``nc_version``: plain ``GET /status.php`` (public, flat JSON, no OCS envelope); returns only ``version``/``versionstring``.
- ``nc_capabilities`` / ``nc_user_info``: curated read-only wrappers over the generic
  OCS escape hatch — ``GET cloud/capabilities`` (enabled apps + versions) and
  ``GET cloud/user`` (profile + quota) via ``client.ocs``.
- ``nc_file_versions`` / ``nc_file_version_restore``: versions DAV — PROPFIND
  ``/remote.php/dav/versions/<user>/versions/<fileid>/`` lists versions (name =
  timestamp); restore = MOVE of the version href to
  ``/remote.php/dav/versions/<user>/restore``, verified by sha256 read-back of the
  live file against the version bytes.
"""

from __future__ import annotations

import hashlib
from urllib.parse import unquote
from xml.sax.saxutils import escape as xml_escape

from . import client, schemas
from .dav import PROPFIND_ALL, PROPFIND_COMMENTS, parse_multistatus, user_path


def _dav_base() -> str:
    """'/remote.php/dav' (single construction site in client)."""
    return client.dav_base()


def _user() -> str:
    """URL-quoted bot user name."""
    return client.dav_user()


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
    try:
        resp = client.propfind(base, depth=1, body=PROPFIND_ALL)
    except client.NcError as exc:
        if exc.status != 404:
            raise
        resp = None  # trash collection itself is gone: nothing can remain
    remaining = [
        r for r in (parse_multistatus(resp.text) if resp is not None else [])
        if unquote(r["href"]).rstrip("/") != base.rstrip("/")
    ]
    if remaining:
        return client.err(f"trash empty verification failed: {len(remaining)} entries remain")
    return client.ok(emptied=True, verified=True)


# --- comments ------------------------------------------------------------------------


def _path_props(path) -> dict:
    """PROPFIND depth 0 on a files path -> its props dict ({} when empty)."""
    rs = parse_multistatus(client.propfind(client.files_dav(path), depth=0, body=PROPFIND_ALL).text)
    return rs[0]["props"] if rs else {}


def _fileid_from_path(path) -> str:
    """Resolve oc:fileid for a files path; 404 if unresolvable."""
    file_id = str(_path_props(path).get("fileid") or "")
    if not file_id:
        raise client.NcError(404, f"could not resolve oc:fileid for {path}")
    return file_id


def _resolve_file_id(args) -> str:
    file_id = str(args.get("file_id") or "")
    if file_id:
        if not file_id.isdigit():
            raise client.NcError(400, "file_id must be numeric")
        return file_id
    path = args.get("path") or ""
    if not path:
        raise client.NcError(400, "give file_id or path")
    return _fileid_from_path(path)


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
    resp = client.propfind(base + "/", depth=1, body=PROPFIND_COMMENTS)
    target = base.rstrip("/")
    out = []
    for r in parse_multistatus(resp.text):
        if unquote(r["href"]).rstrip("/") == target:
            continue
        out.append(_comment_dict(r["props"]))
    return out


def _comment_list(args):
    file_id = _resolve_file_id(args)
    base = f"{_dav_base()}/comments/files/{file_id}"
    comments = _comments_list(base, file_id)
    return client.ok(file_id=file_id, count=len(comments), comments=comments)


def _comment_add(args):
    file_id = _resolve_file_id(args)
    base = f"{_dav_base()}/comments/files/{file_id}"
    message = args.get("message") or ""
    if not message:
        return client.err("message required")
    # NC 35 CommentsPlugin::createComment() is JSON-only: it throws
    # UnsupportedMediaType (415) for XML propertyupdate bodies.
    resp = client.request(
        "POST", base + "/",
        json_body={"actorType": "users", "message": message, "verb": "comment"},
    )
    if resp.status_code not in (200, 201, 204):
        raise client.NcError(resp.status_code, client.resp_message(resp))
    location = resp.headers.get("Content-Location", "")
    comment_id = client.redact(location.rstrip("/").rsplit("/", 1)[-1]) if location else ""
    msgs = [c["message"] for c in _comments_list(base, file_id)]
    if message not in msgs:
        return client.err("add verification failed: message not in read-back", file_id=file_id)
    return client.ok(file_id=file_id, added=True, verified=True,
                     **({"comment_id": comment_id} if comment_id else {}))


def _comment_delete(args):
    file_id = _resolve_file_id(args)
    base = f"{_dav_base()}/comments/files/{file_id}"
    cid = int(args.get("comment_id") or 0)
    if not cid:
        return client.err("comment_id required")
    client.require(client.dav_delete(f"{base}/{cid}"), (200, 204))
    ids = [str(c["id"]) for c in _comments_list(base, file_id) if c["id"]]
    if str(cid) in ids:
        return client.err(f"delete verification failed: comment {cid} still present", file_id=file_id)
    return client.ok(file_id=file_id, comment_id=cid, deleted=True, verified=True)


# --- files_lock (force-unlock) ------------------------------------------------------

# Local PROPFIND body for files_lock lock state; deliberately NOT part of dav.PROPFIND_ALL.
PROPFIND_LOCK = (
    '<?xml version="1.0"?>'
    '<d:propfind xmlns:d="DAV:" xmlns:nc="http://nextcloud.org/ns">'
    "<d:prop><nc:lock/><nc:lock-owner-type/><nc:lock-owner/><nc:lock-owner-editor/></d:prop>"
    "</d:propfind>"
)


def _lock_props(href: str) -> dict:
    rs = parse_multistatus(client.propfind(href, depth=0, body=PROPFIND_LOCK).text)
    return rs[0]["props"] if rs else {}


def _file_unlock(args):
    path = str(args.get("path") or "")
    if not path:
        raise client.NcError(400, "path required")
    href = client.files_dav(path)  # enc_path rejects '.'/'..' segments before any request
    file_id = str(args.get("file_id") or "")
    if file_id:
        if not file_id.isdigit():
            raise client.NcError(400, "file_id must be numeric")
    else:
        # folder check and fileid resolution share one PROPFIND
        props = _path_props(path)
        if props.get("resourcetype") is True:
            return client.err("cannot unlock a folder: files_lock removal works on files only", path=path)
        file_id = str(props.get("fileid") or "")
        if not file_id:
            raise client.NcError(404, f"could not resolve oc:fileid for {path}")
    pre = _lock_props(href)
    if not pre.get("lock"):
        return client.err("file is not locked", status=412, path=path, file_id=file_id)
    # DELETE /ocs/v2.php/apps/files_lock/lock/<fileId>; a 412 racing in here surfaces
    # via client.ocs() as NcError(412, "File is not locked") -> err JSON from the wrapper
    client.ocs("DELETE", f"apps/files_lock/lock/{file_id}")
    if _lock_props(href).get("lock"):
        return client.err("unlock verification failed: file is still locked", path=path, file_id=file_id)
    return client.ok(
        path=path,
        file_id=file_id,
        unlocked=True,
        verified=True,
        lock_owner_type=pre.get("lock-owner-type"),
        lock_owner=pre.get("lock-owner"),
        lock_owner_editor=pre.get("lock-owner-editor"),
    )


# --- generic OCS escape hatch ----------------------------------------------------------


def _ocs(args):
    method = str(args.get("method") or "GET").upper()
    path = str(args.get("path") or "")
    if path.startswith("/") or any(
        unquote(seg) == ".." or "/" in unquote(seg) or "\\" in unquote(seg)
        for seg in path.split("/")
    ):
        return client.err(f"traversal rejected: {path!r}")  # never a request
    if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
        return client.err(f"method must be GET, POST, PUT, DELETE or PATCH, got {method!r}")
    params = args.get("params") or None if method in ("GET", "DELETE") else None
    form = args.get("data") or None if method in ("POST", "PUT", "PATCH") else None
    result = client.ocs(method, path, params=params, data=form)
    return client.ok(method=method, path=path, data=result)


def _version(args):
    resp = client.require(client.request("GET", "/status.php"), (200,))
    try:
        data = resp.json()
    except Exception:
        raise client.NcError(resp.status_code, (resp.text or "")[:300])
    if not isinstance(data, dict):
        raise client.NcError(resp.status_code, "non-dict JSON body from /status.php")
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise client.NcError(resp.status_code, "missing 'version' field in /status.php response")
    versionstring = data.get("versionstring")
    return client.ok(version=version, versionstring=versionstring if isinstance(versionstring, str) else "")


# --- file versions (versions DAV) ---------------------------------------------------


def _versions_base() -> str:
    """'/remote.php/dav/versions/<user>/versions' (per the WebDAV versions doc:
    PROPFIND .../versions/<fileid>/ lists versions, MOVE of a version href to
    .../restore restores it)."""
    return f"{_dav_base()}/versions/{_user()}/versions"


def _file_versions(args):
    path = args.get("path") or ""
    if not path and not args.get("file_id"):
        return client.err("give path or file_id")
    file_id = _resolve_file_id(args)
    base = f"{_versions_base()}/{file_id}/"
    resp = client.propfind(base, depth=1, body=PROPFIND_ALL)
    target = base.rstrip("/")
    out = []
    for r in parse_multistatus(resp.text):
        rhref = unquote(r["href"]).rstrip("/")
        if rhref == target:
            continue
        p = r["props"]
        size = p.get("getcontentlength") or "0"
        out.append({
            "version": rhref.rsplit("/", 1)[-1],  # the timestamp name
            "size": int(size) if str(size).isdigit() else 0,
            "mtime": p.get("getlastmodified"),
        })
    out.sort(key=lambda v: v["version"], reverse=True)
    return client.ok(path=path, file_id=file_id, count=len(out), versions=out)


def _file_version_restore(args):
    path = args["path"]
    version = str(args.get("version") or "")
    if not version:
        return client.err("version required (the timestamp name from nc_file_versions)")
    # enc_path/files_dav reject '.'/'..' segments — validate BOTH args before any
    # request (the nc_ocs convention), so a malformed call never fires the MOVE
    version_seg = client.enc_path(version).lstrip("/")
    live_href = client.files_dav(path)
    file_id = _resolve_file_id(args)
    version_href = f"{_versions_base()}/{file_id}/{version_seg}"
    restore_href = f"{_dav_base()}/versions/{_user()}/restore"
    version_bytes = client.dav_get(version_href).content
    digest = hashlib.sha256(version_bytes).hexdigest()
    resp = client.dav_move(version_href, client.abs_url(restore_href), overwrite=True)
    if resp.status_code not in (200, 201, 204):
        raise client.NcError(resp.status_code, client.resp_message(resp))
    # read-back: the live file must now hold exactly the version's bytes
    live = client.dav_get(live_href).content
    if hashlib.sha256(live).hexdigest() != digest:
        return client.err(
            f"restore verification failed: live file sha256 != version {version} sha256",
            path=path, version=version,
        )
    return client.ok(path=path, file_id=file_id, version=version, sha256=digest, restored=True, verified=True)


def _capabilities(args):
    """GET cloud/capabilities: full tree + a flat {app: version} map for app detection."""
    data = client.ocs("GET", "cloud/capabilities")
    caps = data.get("capabilities") if isinstance(data, dict) else None
    apps = {}
    if isinstance(caps, dict):
        for app, cfg in caps.items():
            version = cfg.get("version") if isinstance(cfg, dict) else None
            apps[str(app)] = version if isinstance(version, str) else ""
    version = data.get("version") if isinstance(data, dict) else None
    return client.ok(
        version=version if isinstance(version, dict) else {},
        apps=apps,
        capabilities=caps if isinstance(caps, dict) else {},
    )


def _user_info(args):
    """GET cloud/user: own profile + quota."""
    data = client.ocs("GET", "cloud/user")
    if not isinstance(data, dict):
        raise client.NcError(200, "unexpected cloud/user payload (not a dict)")
    quota_raw = data.get("quota")
    quota = {k: quota_raw.get(k) for k in ("free", "used", "total", "relative") if isinstance(quota_raw, dict) and k in quota_raw}
    return client.ok(
        id=data.get("id"),
        displayname=data.get("displayname"),
        email=data.get("email"),
        quota=quota,
    )


TOOLS = [
    ("nc_activity", schemas.NC_ACTIVITY, client.tool(_activity)),
    ("nc_notifications", schemas.NC_NOTIFICATIONS, client.tool(_notifications)),
    ("nc_tag_list", schemas.NC_TAG_LIST, client.tool(_tag_list)),
    ("nc_tag_assign", schemas.NC_TAG_ASSIGN, client.tool(_tag_assign)),
    ("nc_tag_unassign", schemas.NC_TAG_UNASSIGN, client.tool(_tag_unassign)),
    ("nc_trash_list", schemas.NC_TRASH_LIST, client.tool(_trash_list)),
    ("nc_trash_restore", schemas.NC_TRASH_RESTORE, client.tool(_trash_restore)),
    ("nc_trash_empty", schemas.NC_TRASH_EMPTY, client.tool(_trash_empty)),
    ("nc_comment_list", schemas.NC_COMMENT_LIST, client.tool(_comment_list)),
    ("nc_comment_add", schemas.NC_COMMENT_ADD, client.tool(_comment_add)),
    ("nc_comment_delete", schemas.NC_COMMENT_DELETE, client.tool(_comment_delete)),
    ("nc_ocs", schemas.NC_OCS, client.tool(_ocs)),
    ("nc_file_unlock", schemas.NC_FILE_UNLOCK, client.tool(_file_unlock)),
    ("nc_version", schemas.NC_VERSION, client.tool(_version)),
    ("nc_capabilities", schemas.NC_CAPABILITIES, client.tool(_capabilities)),
    ("nc_user_info", schemas.NC_USER_INFO, client.tool(_user_info)),
    ("nc_file_versions", schemas.NC_FILE_VERSIONS, client.tool(_file_versions)),
    ("nc_file_version_restore", schemas.NC_FILE_VERSION_RESTORE, client.tool(_file_version_restore)),
]
