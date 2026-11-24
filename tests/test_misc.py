"""Misc handlers: tags, trashbin, comments, activity, file unlock, file versions."""

import hashlib
import json

import httpx
from conftest import FILES_DAV, TRASH_DAV, VERSIONS_DAV, multistatus, ocs_err, ocs_ok


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
        if req.method == "PROPFIND" and p.startswith(TRASH_DAV):
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
    assert restored["dest"] == f"https://nc.example{FILES_DAV}/Docs/a.txt"


def test_comment_list_resolves_path_to_fileid(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p.startswith(FILES_DAV):
            return multistatus([(p, "<oc:fileid>4242</oc:fileid>")])
        if p.startswith("/remote.php/dav/comments/files/4242"):
            return multistatus([
                ("/remote.php/dav/comments/files/4242", ""),
                ("/remote.php/dav/comments/files/4242/1",
                 "<oc:id>1</oc:id><oc:message>hi there</oc:message><oc:actorDisplayName>bot</oc:actorDisplayName>"),
            ])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_comment_list", {"path": "/a.txt"})
    assert res["ok"] and res["file_id"] == "4242"
    assert res["comments"][0]["message"] == "hi there" and res["comments"][0]["actor"] == "bot"


def test_comment_list_propfind_requests_oc_props(nc, call):
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
    res = call("nc_comment_list", {"file_id": "4242"})
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


def test_comment_add_posts_json_and_verifies(nc, call):
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
    res = call("nc_comment_add", {"file_id": "4242", "message": "hello"})
    assert res["ok"] and res["added"] and res["verified"] and res["comment_id"] == "10207"
    assert posted["content_type"].startswith("application/json")
    assert json.loads(posted["body"]) == {"actorType": "users", "message": "hello", "verb": "comment"}
    assert all(b"propertyupdate" not in r.content for r in nc.requests)


def test_comment_add_server_error_returns_err_json(nc, call):
    def h(req):
        if req.method == "POST" and "/comments/files/4242" in req.url.path:
            return httpx.Response(415, text="Unsupported Media Type")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_comment_add", {"file_id": "4242", "message": "hello"})
    assert res["ok"] is False and "415" in res["error"]


def test_comment_add_readback_mismatch_returns_err(nc, call):
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
    res = call("nc_comment_add", {"file_id": "4242", "message": "hello"})
    assert res["ok"] is False and "verification failed" in res["error"]


def test_comment_delete_verifies_gone(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "DELETE" and p == "/remote.php/dav/comments/files/4242/7":
            return httpx.Response(204)
        if req.method == "PROPFIND" and p.startswith("/remote.php/dav/comments/files/4242"):
            return multistatus([
                ("/remote.php/dav/comments/files/4242", ""),
                ("/remote.php/dav/comments/files/4242/9",
                 "<oc:id>9</oc:id><oc:message>other</oc:message>"),
            ])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_comment_delete", {"file_id": "4242", "comment_id": 7})
    assert res["ok"] and res["deleted"] and res["verified"] and res["comment_id"] == 7
    assert any(r.method == "DELETE" and r.url.path == "/remote.php/dav/comments/files/4242/7"
               for r in nc.requests)


def test_comment_delete_readback_mismatch_returns_err(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "DELETE" and p == "/remote.php/dav/comments/files/4242/7":
            return httpx.Response(204)
        if req.method == "PROPFIND" and p.startswith("/remote.php/dav/comments/files/4242"):
            return multistatus([
                ("/remote.php/dav/comments/files/4242", ""),
                ("/remote.php/dav/comments/files/4242/7",
                 "<oc:id>7</oc:id><oc:message>still here</oc:message>"),
            ])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_comment_delete", {"file_id": "4242", "comment_id": 7})
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


def test_file_unlock_via_path_resolves_deletes_and_verifies(nc, call):
    lock_reads = {"n": 0}

    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p == f"{FILES_DAV}/a.txt":
            if b"calendar-data" in req.content:  # resolution PROPFIND (PROPFIND_ALL)
                return multistatus([(p, "<oc:fileid>195509</oc:fileid><d:resourcetype/>")])
            if b"nc:lock" in req.content:  # lock-state PROPFIND (PROPFIND_LOCK)
                lock_reads["n"] += 1
                if lock_reads["n"] == 1:
                    return multistatus([(p,
                        '<nc:lock xmlns:nc="http://nextcloud.org/ns">1</nc:lock>'
                        '<nc:lock-owner-type xmlns:nc="http://nextcloud.org/ns">1</nc:lock-owner-type>'
                        '<nc:lock-owner-editor xmlns:nc="http://nextcloud.org/ns">Text</nc:lock-owner-editor>')])
                return multistatus([(p, '<nc:lock xmlns:nc="http://nextcloud.org/ns"></nc:lock>')])
        if req.method == "DELETE" and p == "/ocs/v2.php/apps/files_lock/lock/195509":
            return ocs_ok([])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_unlock", {"path": "/a.txt"})
    assert res["ok"] and res["verified"] and res["unlocked"]
    assert res["file_id"] == "195509"
    assert res["lock_owner_type"] == "1" and res["lock_owner_editor"] == "Text"
    assert nc.methods() == ["PROPFIND", "PROPFIND", "DELETE", "PROPFIND"]
    deletes = nc.find("DELETE", "files_lock")
    assert len(deletes) == 1
    assert deletes[0].url.path == "/ocs/v2.php/apps/files_lock/lock/195509"
    assert deletes[0].headers["OCS-APIRequest"] == "true"


def test_file_unlock_with_file_id_skips_resolution(nc, call):
    state = {"deleted": False}

    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p == f"{FILES_DAV}/a.txt":
            lock = ('<nc:lock xmlns:nc="http://nextcloud.org/ns">1</nc:lock>'
                    if not state["deleted"] else
                    '<nc:lock xmlns:nc="http://nextcloud.org/ns"></nc:lock>')
            return multistatus([(p, lock)])
        if req.method == "DELETE" and p == "/ocs/v2.php/apps/files_lock/lock/42":
            state["deleted"] = True
            return ocs_ok([])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_unlock", {"path": "/a.txt", "file_id": "42"})
    assert res["ok"] and res["verified"] and res["file_id"] == "42"
    assert nc.methods() == ["PROPFIND", "DELETE", "PROPFIND"]
    assert nc.find("DELETE", "files_lock")[0].url.path.endswith("/lock/42")


def test_file_unlock_not_locked_errors_without_delete(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p == f"{FILES_DAV}/a.txt":
            if b"calendar-data" in req.content:
                return multistatus([(p, "<oc:fileid>9</oc:fileid><d:resourcetype/>")])
            return multistatus([(p, '<nc:lock xmlns:nc="http://nextcloud.org/ns"></nc:lock>')])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_unlock", {"path": "/a.txt"})
    assert res["ok"] is False and "not locked" in res["error"]
    assert res.get("status") == 412
    assert nc.find("DELETE", "files_lock") == []


def test_file_unlock_delete_412_surfaces_as_err(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p == f"{FILES_DAV}/a.txt":
            if b"calendar-data" in req.content:
                return multistatus([(p, "<oc:fileid>9</oc:fileid><d:resourcetype/>")])
            return multistatus([(p, '<nc:lock xmlns:nc="http://nextcloud.org/ns">1</nc:lock>')])
        if req.method == "DELETE" and "files_lock" in p:
            return ocs_err(412, "File is not locked", http=412)
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_unlock", {"path": "/a.txt"})
    assert res["ok"] is False and "412" in res["error"] and "File is not locked" in res["error"]


def test_file_unlock_folder_rejected(nc, call):
    def h(req):
        if req.method == "PROPFIND" and req.url.path == f"{FILES_DAV}/a.txt":
            return multistatus([(f"{FILES_DAV}/a.txt",
                                 "<d:resourcetype><d:collection/></d:resourcetype><oc:fileid>7</oc:fileid>")])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_unlock", {"path": "/a.txt"})
    assert res["ok"] is False and "folder" in res["error"]
    assert nc.find("DELETE", "files_lock") == []


def test_file_unlock_readback_still_locked_fails(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p == f"{FILES_DAV}/a.txt":
            if b"calendar-data" in req.content:
                return multistatus([(p, "<oc:fileid>9</oc:fileid><d:resourcetype/>")])
            return multistatus([(p, '<nc:lock xmlns:nc="http://nextcloud.org/ns">1</nc:lock>')])
        if req.method == "DELETE" and "files_lock" in p:
            return ocs_ok([])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_unlock", {"path": "/a.txt"})
    assert res["ok"] is False and "verification failed" in res["error"]


def test_file_unlock_nonnumeric_file_id_rejected(nc, call):
    nc.handler = lambda req: httpx.Response(404, text="nf")
    res = call("nc_file_unlock", {"path": "/a.txt", "file_id": "12/../../x"})
    assert res["ok"] is False and "file_id must be numeric" in res["error"]
    assert nc.requests == []


def test_file_unlock_traversal_path_rejected_before_request(nc, call):
    nc.handler = lambda req: httpx.Response(404, text="nf")
    res = call("nc_file_unlock", {"path": "/../x"})
    assert res["ok"] is False
    assert nc.requests == []


def test_version_returns_only_version_fields(nc, call):
    nc.handler = lambda req: httpx.Response(200, json={
        "installed": True, "maintenance": False, "needsDbUpgrade": False,
        "version": "35.0.2.2", "versionstring": "35.0.2", "edition": "",
        "productname": "Nextcloud", "extendedSupport": False,
    })
    res = call("nc_version", {})
    assert res == {"ok": True, "version": "35.0.2.2", "versionstring": "35.0.2"}
    reqs = nc.find("GET", "/status.php")
    assert len(reqs) == 1 and len(nc.requests) == 1


def test_version_non_200_returns_err(nc, call):
    nc.handler = lambda req: httpx.Response(503, text="down")
    res = call("nc_version", {})
    assert res["ok"] is False and "503" in res["error"]


def test_version_non_dict_json_returns_err(nc, call):
    nc.handler = lambda req: httpx.Response(200, json=["not", "a", "dict"])
    res = call("nc_version", {})
    assert res["ok"] is False


def test_version_missing_version_field_returns_err(nc, call):
    nc.handler = lambda req: httpx.Response(200, json={"installed": True})
    res = call("nc_version", {})
    assert res["ok"] is False and "version" in res["error"]


def test_trash_empty_tolerates_404_on_verification_propfind(nc, call):
    def h(req):
        if req.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, text="gone")  # trash collection itself vanished

    nc.handler = h
    res = call("nc_trash_empty", {})
    assert res["ok"] is True and res["emptied"] is True and res["verified"] is True


# --- capabilities / user info (curated nc_ocs wrappers) ------------------------------


def test_capabilities_returns_apps_map(nc, call):
    def h(req):
        assert req.method == "GET" and req.url.path == "/ocs/v2.php/cloud/capabilities"
        return ocs_ok({
            "version": {"major": 35, "string": "35.0.2"},
            "capabilities": {
                "spreed": {"version": "21.0.0", "features": ["chat"]},
                "deck": {"version": "1.15.0"},
                "files": {"version": "35.0.2"},
            },
        })

    nc.handler = h
    res = call("nc_capabilities", {})
    assert res["ok"] is True
    assert res["apps"] == {"spreed": "21.0.0", "deck": "1.15.0", "files": "35.0.2"}
    assert res["version"]["string"] == "35.0.2"
    assert "spreed" in res["capabilities"]
    assert nc.methods() == ["GET"]


def test_capabilities_ocs_error_returns_err(nc, call):
    nc.handler = lambda req: ocs_err(404, "App not found")
    res = call("nc_capabilities", {})
    assert res["ok"] is False and "404" in res["error"]


def test_user_info_returns_quota(nc, call):
    def h(req):
        assert req.method == "GET" and req.url.path == "/ocs/v2.php/cloud/user"
        return ocs_ok({
            "id": "bot",
            "displayname": "Bot",
            "email": "bot@example.com",
            "quota": {"free": 1000, "used": 500, "total": 1500, "relative": 33.3},
            "enabled": True,
        })

    nc.handler = h
    res = call("nc_user_info", {})
    assert res["ok"] is True
    assert res["id"] == "bot" and res["displayname"] == "Bot"
    assert res["quota"] == {"free": 1000, "used": 500, "total": 1500, "relative": 33.3}


def test_user_info_non_dict_payload_returns_err(nc, call):
    nc.handler = lambda req: ocs_ok(["not", "a", "dict"])
    res = call("nc_user_info", {})
    assert res["ok"] is False


# --- file versions (versions DAV) ---------------------------------------------------


def test_file_versions_resolves_fileid_then_lists(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p == f"{FILES_DAV}/a.txt":
            assert req.headers["Depth"] == "0"
            return multistatus([(p, "<oc:fileid>42</oc:fileid>")])
        if req.method == "PROPFIND" and p == f"{VERSIONS_DAV}/42/":
            assert req.headers["Depth"] == "1"
            return multistatus([
                (f"{VERSIONS_DAV}/42/", "<d:resourcetype><d:collection/></d:resourcetype>"),
                (f"{VERSIONS_DAV}/42/1700000001",
                 "<d:getcontentlength>11</d:getcontentlength>"
                 "<d:getlastmodified>Wed, 15 Nov 2023 00:00:01 GMT</d:getlastmodified>"),
                (f"{VERSIONS_DAV}/42/1700000002",
                 "<d:getcontentlength>22</d:getcontentlength>"
                 "<d:getlastmodified>Thu, 16 Nov 2023 00:00:02 GMT</d:getlastmodified>"),
            ])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_versions", {"path": "/a.txt"})
    assert res["ok"] is True and res["file_id"] == "42" and res["count"] == 2
    # newest timestamp first; the version name is the last href segment
    assert [v["version"] for v in res["versions"]] == ["1700000002", "1700000001"]
    assert res["versions"][0]["size"] == 22 and res["versions"][0]["mtime"].endswith("GMT")
    assert nc.methods() == ["PROPFIND", "PROPFIND"]


def test_file_versions_with_file_id_skips_path_propfind(nc, call):
    def h(req):
        assert req.method == "PROPFIND" and req.url.path == f"{VERSIONS_DAV}/42/"
        return multistatus([(f"{VERSIONS_DAV}/42/1700000001", "<d:getcontentlength>5</d:getcontentlength>")])

    nc.handler = h
    res = call("nc_file_versions", {"path": "/a.txt", "file_id": "42"})
    assert res["ok"] is True and res["count"] == 1
    assert nc.methods() == ["PROPFIND"]


def test_file_versions_requires_path_or_file_id(nc, call):
    nc.handler = lambda req: httpx.Response(404, text="nf")
    res = call("nc_file_versions", {})
    assert res["ok"] is False and "path or file_id" in res["error"]
    assert nc.requests == []


def test_file_version_restore_verified_by_readback(nc, call):
    moved = {}

    def h(req):
        p = req.url.path
        if req.method == "PROPFIND" and p == f"{FILES_DAV}/a.txt":
            return multistatus([(p, "<oc:fileid>42</oc:fileid>")])
        if req.method == "GET" and p == f"{VERSIONS_DAV}/42/1700000001":
            return httpx.Response(200, content=b"old-bytes")
        if req.method == "MOVE" and p == f"{VERSIONS_DAV}/42/1700000001":
            moved["dest"] = req.headers["Destination"]
            assert req.headers["Overwrite"] == "T"
            return httpx.Response(201)
        if req.method == "GET" and p == f"{FILES_DAV}/a.txt":
            return httpx.Response(200, content=b"old-bytes")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_version_restore", {"path": "/a.txt", "version": "1700000001"})
    assert res["ok"] is True and res["restored"] is True and res["verified"] is True
    assert res["sha256"] == hashlib.sha256(b"old-bytes").hexdigest()
    assert moved["dest"] == "https://nc.example/remote.php/dav/versions/bot/restore"
    assert nc.methods() == ["PROPFIND", "GET", "MOVE", "GET"]


def test_file_version_restore_readback_mismatch_fails(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "GET" and p.startswith(VERSIONS_DAV):
            return httpx.Response(200, content=b"old-bytes")
        if req.method == "MOVE":
            return httpx.Response(201)
        if req.method == "GET" and p.startswith(FILES_DAV):
            return httpx.Response(200, content=b"other-bytes")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_version_restore", {"path": "/a.txt", "file_id": "42", "version": "1700000001"})
    assert res["ok"] is False and "verification failed" in res["error"]
    # the MOVE happened; only the read-back caught the mismatch
    assert nc.find("MOVE", VERSIONS_DAV) and nc.find("GET", FILES_DAV)


def test_file_version_restore_requires_version(nc, call):
    nc.handler = lambda req: httpx.Response(404, text="nf")
    res = call("nc_file_version_restore", {"path": "/a.txt"})
    assert res["ok"] is False and "version required" in res["error"]
    assert nc.requests == []


def test_file_version_restore_traversal_version_rejected_before_request(nc, call):
    nc.handler = lambda req: httpx.Response(404, text="nf")
    res = call("nc_file_version_restore", {"path": "/a.txt", "file_id": "42", "version": "../evil"})
    assert res["ok"] is False and "traversal" in res["error"]
    assert nc.requests == []


def test_file_version_restore_traversal_version_rejected_before_fileid_propfind(nc, call):
    # path-only form: the version must be validated BEFORE the path->oc:fileid PROPFIND
    nc.handler = lambda req: httpx.Response(404, text="nf")
    res = call("nc_file_version_restore", {"path": "/a.txt", "version": "../evil"})
    assert res["ok"] is False and "traversal" in res["error"]
    assert nc.requests == []


def test_file_version_restore_traversal_path_rejected_before_any_request(nc, call):
    # file_id given, but the path itself traverses: rejected before the MOVE
    nc.handler = lambda req: httpx.Response(404, text="nf")
    res = call("nc_file_version_restore", {"path": "../x", "file_id": "42", "version": "1700000001"})
    assert res["ok"] is False and "traversal" in res["error"]
    assert nc.requests == []


def test_file_version_restore_move_failure_surfaces_as_err(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "GET" and p.startswith(VERSIONS_DAV):
            return httpx.Response(200, content=b"old-bytes")
        if req.method == "MOVE":
            return httpx.Response(403, text="Forbidden")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_version_restore", {"path": "/a.txt", "file_id": "42", "version": "1700000001"})
    assert res["ok"] is False and "403" in res["error"]
    assert nc.find("GET", FILES_DAV) == []  # no read-back after a failed MOVE
