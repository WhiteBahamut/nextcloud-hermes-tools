"""Shares tools — OCS ``/ocs/v2.php/apps/files_sharing/api/v1/shares``.

POST uses form encoding (``data=``, not ``json=``). Create is verified by a
follow-up ``GET /shares?path=<path>`` containing the new share id; delete is
verified by a 404 on the follow-up GET. ``nc_share_edit`` uses
``PUT /shares/{id}`` (fields per ShareAPIController::updateShare: permissions,
password, expireDate, note) and is verified by a follow-up ``GET /shares/{id}``.
shareType 0 = user/group share, permissions 31 = all.
"""

from __future__ import annotations

from . import client, schemas

BASE = "apps/files_sharing/api/v1/shares"


def _list(args):
    path = args.get("path") or ""
    params = {"path": path} if path else None
    data = client.ocs("GET", BASE, params=params)
    shares = data if isinstance(data, list) else []
    return client.ok(count=len(shares), shares=shares)


def _create(args):
    path = args["path"]
    share_with = args["share_with"]
    share_type = int(args.get("share_type") or 0)
    permissions = int(args.get("permissions") if args.get("permissions") is not None else 1)
    note = args.get("note") or ""
    form = {
        "path": path,
        "shareType": share_type,
        "shareWith": share_with,
        "permissions": permissions,
    }
    if note:
        form["note"] = note
    created = client.ocs("POST", BASE, data=form)
    if not isinstance(created, dict) or "id" not in created:
        return client.err(f"share create returned no id: {created!r}", path=path)
    share_id = created["id"]
    # read-back: the new id must appear in GET /shares?path=<path>
    existing = client.ocs("GET", BASE, params={"path": path})
    ids = {str(s.get("id")) for s in (existing or []) if isinstance(s, dict)}
    if str(share_id) not in ids:
        return client.err(f"share create verification failed: id {share_id} not in shares for {path}", path=path)
    return client.ok(id=share_id, path=path, share_with=share_with, verified=True, share=created)


def _delete(args):
    share_id = int(args["id"])
    client.ocs("DELETE", f"{BASE}/{share_id}")
    # verify 404 on follow-up GET
    try:
        client.ocs("GET", f"{BASE}/{share_id}")
    except client.NcError as exc:
        if exc.status == 404:
            return client.ok(id=share_id, deleted=True, verified=True)
        raise
    return client.err(f"share delete verification failed: id {share_id} still readable")


def _edit(args):
    share_id = int(args["id"])
    form = {}
    if args.get("permissions") is not None:
        form["permissions"] = int(args["permissions"])
    if "password" in args:
        form["password"] = args.get("password") or ""
    if "expire_date" in args:
        form["expireDate"] = args.get("expire_date") or ""
    if "note" in args:
        form["note"] = args.get("note") or ""
    if not form:
        return client.err("nothing to edit: provide permissions, password, expire_date and/or note", id=share_id)
    client.ocs("PUT", f"{BASE}/{share_id}", data=form)
    got = client.ocs("GET", f"{BASE}/{share_id}")
    if not isinstance(got, dict):
        return client.err(f"share edit verification failed: GET returned {got!r}", id=share_id)
    problems = []
    if "permissions" in form and int(got.get("permissions") or 0) != form["permissions"]:
        problems.append(f"permissions: got {got.get('permissions')!r} != {form['permissions']}")
    if "note" in form and (got.get("note") or "") != form["note"]:
        problems.append(f"note: got {got.get('note')!r} != {form['note']!r}")
    if "expireDate" in form:
        got_exp = str(got.get("expiration") or got.get("expireDate") or "")[:10]
        if got_exp != form["expireDate"]:
            problems.append(f"expireDate: got {got_exp!r} != {form['expireDate']!r}")
    # password is never echoed by the API; the successful GET above is its verification
    if problems:
        return client.err("share edit verification failed: " + "; ".join(problems), id=share_id)
    return client.ok(id=share_id, verified=True, share=got)


TOOLS = [
    ("nc_share_list", schemas.NC_SHARE_LIST, client.tool(_list)),
    ("nc_share_create", schemas.NC_SHARE_CREATE, client.tool(_create)),
    ("nc_share_delete", schemas.NC_SHARE_DELETE, client.tool(_delete)),
    ("nc_share_edit", schemas.NC_SHARE_EDIT, client.tool(_edit)),
]
