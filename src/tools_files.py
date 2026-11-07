"""Files tools — WebDAV under ``/remote.php/dav/files/<user>/``.

Server quirks baked in: explicit ``Depth`` on every PROPFIND, 200 **and** 207
accepted, every path segment URL-encoded, MOVE 423 (files_lock) -> GET bytes ->
PUT destination -> DELETE source (only after the PUT succeeded). Every write is
verified by read-back; delete is verified 404.
"""

from __future__ import annotations

import base64
import logging
from urllib.parse import unquote

from . import client, schemas
from .dav import PROPFIND_ALL, entry_from_response, parse_multistatus

log = logging.getLogger(__name__)


def _prefix() -> str:
    """DAV href prefix of the bot's files root, no trailing slash."""
    return client.files_dav("/").rstrip("/")


def _list(args):
    path = args.get("path") or "/"
    depth = str(args.get("depth") or "1")
    if depth not in ("0", "1", "infinity"):
        return client.err(f"invalid depth {depth!r}: use 0, 1 or infinity")
    limit = int(args.get("limit") or 200)
    href = client.files_dav(path)
    prefix = _prefix()
    resp = client.propfind(href, depth=depth, body=PROPFIND_ALL)
    target = href.rstrip("/")
    entries = []
    for r in parse_multistatus(resp.text):
        rhref = unquote(r["href"]).rstrip("/")
        if rhref == target and depth != "0":
            continue  # the queried collection itself
        entries.append(entry_from_response(r, prefix))
        if len(entries) >= limit:
            break
    return client.ok(path=path, depth=depth, count=len(entries), entries=entries)


def _get(args):
    path = args["path"]
    raw = bool(args.get("raw"))
    max_bytes = int(args.get("max_bytes") if args.get("max_bytes") is not None else 100000)
    if max_bytes < 0:
        return client.err(f"invalid max_bytes {max_bytes}: use 0 (unlimited) or a positive byte count")
    resp = client.dav_get(client.files_dav(path))
    size = len(resp.content)
    etag = resp.headers.get("etag")
    truncated = 0 < max_bytes < size
    data = resp.content[:max_bytes] if truncated else resp.content
    extra = {"truncated": True, "max_bytes": max_bytes} if truncated else {}
    if not raw:
        try:
            return client.ok(path=path, size=size, etag=etag, content=data.decode("utf-8"), **extra)
        except UnicodeDecodeError:
            pass  # byte slice cut a multi-byte char -> base64 of the slice below
    return client.ok(
        path=path, size=size, etag=etag, content_base64=base64.b64encode(data).decode("ascii"), **extra
    )


def _put(args):
    path = args["path"]
    if args.get("content_base64"):
        data = base64.b64decode(args["content_base64"])
    else:
        data = (args.get("content") or "").encode("utf-8")
    href = client.files_dav(path)
    try:
        client.put_verified(href, data, content_type=args.get("content_type") or "")
    except client.NcError as exc:
        return client.err(f"{exc.message}: {path}", status=exc.status, path=path)
    return client.ok(path=path, size=len(data), verified=True)


def _mkdir(args):
    path = args["path"]
    href = client.files_dav(path)
    try:
        client.dav_mkcol(href)
    except client.NcError as exc:
        if exc.status != 405:  # 405 = already exists
            raise
    if not client.verify_exists(href):
        return client.err(f"mkdir verification failed: {path}", path=path)
    return client.ok(path=path, created=True, verified=True)


def _move(args):
    source = args["source"]
    destination = args["destination"]
    overwrite = args.get("overwrite", True)
    src_href = client.files_dav(source)
    dst_href = client.files_dav(destination)
    resp = client.dav_move(src_href, client.abs_url(dst_href), overwrite=overwrite)
    used_fallback = False
    if resp.status_code == 423:
        # files_lock: strict order GET source bytes -> PUT destination -> DELETE source.
        log.info("MOVE 423 files_lock, fallback GET/PUT/DELETE for %s", client.redact(source))
        data = client.dav_get(src_href).content
        used_fallback = True
        try:
            client.put_verified(dst_href, data)
        except client.NcError as exc:
            return client.err(
                f"move fallback verification failed ({exc.message}): {destination}",
                status=exc.status,
                source=source,
                destination=destination,
            )
        client.require(client.dav_delete(src_href), (200, 204))
    elif resp.status_code not in (200, 201, 204):
        raise client.NcError(resp.status_code, client.resp_message(resp))
    if not client.verify_exists(dst_href):
        return client.err(
            f"move verification failed: destination missing {destination}",
            source=source,
            destination=destination,
        )
    return client.ok(source=source, destination=destination, verified=True, fallback=used_fallback)


def _delete(args):
    path = args["path"]
    href = client.files_dav(path)
    client.require(client.dav_delete(href), (200, 204))
    if not client.verify_gone(href):
        return client.err(f"delete verification failed: still present {path}", path=path)
    return client.ok(path=path, deleted=True, verified=True)


TOOLS = [
    ("nc_file_list", schemas.NC_FILE_LIST, client.tool(_list)),
    ("nc_file_get", schemas.NC_FILE_GET, client.tool(_get)),
    ("nc_file_put", schemas.NC_FILE_PUT, client.tool(_put)),
    ("nc_file_mkdir", schemas.NC_FILE_MKDIR, client.tool(_mkdir)),
    ("nc_file_move", schemas.NC_FILE_MOVE, client.tool(_move)),
    ("nc_file_delete", schemas.NC_FILE_DELETE, client.tool(_delete)),
]
