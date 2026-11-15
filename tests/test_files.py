import httpx
from conftest import multistatus

FILES = "/remote.php/dav/files/bot"


def test_file_list_parses_multistatus(nc, call):
    nc.handler = lambda req: multistatus([
        (f"{FILES}/", '<d:resourcetype><d:collection/></d:resourcetype><oc:fileid>1</oc:fileid>'),
        (f"{FILES}/Docs", '<d:resourcetype><d:collection/></d:resourcetype><d:getlastmodified>Mon, 02 Nov 2026 10:00:00 GMT</d:getlastmodified>'),
        (f"{FILES}/a%20b.txt", '<d:resourcetype/><d:getcontentlength>5</d:getcontentlength><d:getcontenttype>text/plain</d:getcontenttype><d:getetag>&quot;e1&quot;</d:getetag>'),
    ])
    res = call("nc_file_list", {"path": "/"})
    assert res["ok"] and res["count"] == 2
    assert nc.requests[0].method == "PROPFIND"
    assert nc.requests[0].headers["Depth"] == "1"  # explicit Depth (int 1 default)
    by_name = {e["name"]: e for e in res["entries"]}
    assert set(by_name) == {"Docs", "a b.txt"}  # href URL-decoded
    assert by_name["Docs"]["is_dir"] is True
    f = by_name["a b.txt"]
    assert f["is_dir"] is False and f["size"] == 5 and f["content_type"] == "text/plain" and f["etag"] == '"e1"'


def test_file_list_invalid_depth(nc, call):
    res = call("nc_file_list", {"path": "/", "depth": "2"})
    assert res["ok"] is False


def test_file_list_depth_forms(nc, call):
    nc.handler = lambda req: multistatus([(f"{FILES}/", '<d:resourcetype><d:collection/></d:resourcetype>')])
    for depth, header in ((1, "1"), ("1", "1"), ("0", "0"), ("infinity", "infinity")):
        res = call("nc_file_list", {"path": "/", "depth": depth})
        assert res["ok"] and res["depth"] == str(depth), depth
        assert nc.requests[-1].headers["Depth"] == header
    res = call("nc_file_list", {"path": "/", "recursive": True})
    assert res["ok"] and res["depth"] == "infinity"
    assert nc.requests[-1].headers["Depth"] == "infinity"
    n = len(nc.requests)
    res = call("nc_file_list", {"path": "/", "depth": 2})
    assert res["ok"] is False and len(nc.requests) == n  # rejected before any request


def test_file_get_text_and_base64(nc, call):
    def h(req):
        if req.url.path == f"{FILES}/t.txt":
            return httpx.Response(200, content="héllo wörld".encode("utf-8"))
        return httpx.Response(200, content=b"\x00\x01\x02\xff")

    nc.handler = h
    res = call("nc_file_get", {"path": "/t.txt"})
    assert res["ok"] and res["content"] == "héllo wörld"
    res = call("nc_file_get", {"path": "/bin.dat"})
    assert res["ok"] and "content_base64" in res and "content" not in res
    res = call("nc_file_get", {"path": "/t.txt", "raw": True})
    assert "content_base64" in res


def test_file_put_readback_ok(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "PUT":
            state[p] = req.content
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, content=state[p]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_put", {"path": "/x.txt", "content": "hello"})
    assert res["ok"] and res["verified"] is True and res["size"] == 5


def test_file_put_readback_mismatch_fails(nc, call):
    def h(req):
        if req.method == "PUT":
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, content=b"tampered")  # sha256 mismatch
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_put", {"path": "/x.txt", "content": "hello"})
    assert res["ok"] is False and "verification" in res["error"]


def test_file_put_empty_rejected_before_any_request(nc, call):
    nc.handler = lambda req: httpx.Response(500, text="must not be called")
    res = call("nc_file_put", {"path": "/x.txt"})
    assert res["ok"] is False and "empty content" in res["error"]
    assert nc.requests == []  # rejected before any HTTP request
    res = call("nc_file_put", {"path": "/x.txt", "content": ""})
    assert res["ok"] is False and nc.requests == []


def test_file_put_allow_empty_writes_zero_bytes(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "PUT":
            state[p] = req.content
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, content=state[p]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_put", {"path": "/empty.txt", "allow_empty": True})
    assert res["ok"] and res["verified"] is True and res["size"] == 0
    puts = [r for r in nc.requests if r.method == "PUT"]
    assert len(puts) == 1 and puts[0].content == b""


def test_file_copy_happy_path_request_order_and_verify(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "PROPFIND":
            if p == f"{FILES}/src.txt":
                return multistatus([(f"{FILES}/src.txt", '<d:resourcetype/><d:getcontenttype>text/plain</d:getcontenttype>')])
            return httpx.Response(404, text="nf")  # destination absent
        if req.method == "GET" and p == f"{FILES}/src.txt":
            return httpx.Response(200, content=b"copy me")
        if req.method == "PUT":
            state[p] = req.content
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, content=state[p]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_copy", {"source": "/src.txt", "destination": "/dst.txt"})
    assert res["ok"] and res["verified"] is True and res["size"] == 7
    assert [r.method for r in nc.requests] == ["PROPFIND", "GET", "PUT", "GET"]  # find -> read -> write -> read-back
    put = nc.requests[2]
    assert put.headers.get("Content-Type") == "text/plain" and put.content == b"copy me"


def test_file_copy_rejects_folder_source(nc, call):
    def h(req):
        if req.method == "PROPFIND":
            return multistatus([(f"{FILES}/Docs", '<d:resourcetype><d:collection/></d:resourcetype>')])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_copy", {"source": "/Docs", "destination": "/Docs2"})
    assert res["ok"] is False and "files only" in res["error"]
    assert [r.method for r in nc.requests] == ["PROPFIND"]  # no GET/PUT


def test_file_copy_destination_exists_without_overwrite(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPFIND":
            if p == f"{FILES}/src.txt":
                return multistatus([(f"{FILES}/src.txt", '<d:resourcetype/>')])
            return multistatus([(p, '<d:resourcetype/>')])  # destination exists
        if req.method == "GET":
            return httpx.Response(200, content=b"data")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_copy", {"source": "/src.txt", "destination": "/dst.txt", "overwrite": False})
    assert res["ok"] is False and "destination exists" in res["error"]
    assert not any(r.method == "PUT" for r in nc.requests)


def test_file_copy_rejects_traversal_and_same_path_before_request(nc, call):
    nc.handler = lambda req: httpx.Response(500, text="must not be called")
    res = call("nc_file_copy", {"source": "/../x.txt", "destination": "/y.txt"})
    assert res["ok"] is False and nc.requests == []
    res = call("nc_file_copy", {"source": "/a.txt", "destination": "/a.txt"})
    assert res["ok"] is False and nc.requests == []


def test_file_copy_readback_mismatch_fails(nc, call):
    def h(req):
        p = req.url.path
        if req.method == "PROPFIND":
            return multistatus([(f"{FILES}/src.txt", '<d:resourcetype/>')]) if p == f"{FILES}/src.txt" else httpx.Response(404, text="nf")
        if req.method == "GET" and p == f"{FILES}/src.txt":
            return httpx.Response(200, content=b"original")
        if req.method == "PUT":
            return httpx.Response(201)
        if req.method == "GET":  # verification read-back returns tampered bytes
            return httpx.Response(200, content=b"tampered")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_copy", {"source": "/src.txt", "destination": "/dst.txt"})
    assert res["ok"] is False and "verification" in res["error"]
    assert any(r.method == "PUT" for r in nc.requests)


def test_move_423_fallback_order_put_before_delete(nc, call):
    state = {f"{FILES}/src.txt": b"data123"}

    def h(req):
        p = req.url.path.rstrip("/")
        if req.method == "MOVE":
            return httpx.Response(423, text="files_lock")
        if req.method == "GET":
            return httpx.Response(200, content=state[p]) if p in state else httpx.Response(404, text="nf")
        if req.method == "PUT":
            state[p] = req.content
            return httpx.Response(201)
        if req.method == "DELETE":
            state.pop(p, None)
            return httpx.Response(204)
        if req.method == "PROPFIND":
            if p in state or p == FILES:
                return multistatus([(req.url.path, "<d:resourcetype/>")])
            return httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_move", {"source": "/src.txt", "destination": "/dst.txt"})
    assert res["ok"] and res["verified"] is True and res["fallback"] is True
    methods = nc.methods()
    assert methods[0] == "MOVE"
    assert methods.index("PUT") < methods.index("DELETE")  # strict order: PUT before DELETE
    assert f"{FILES}/dst.txt" in state and f"{FILES}/src.txt" not in state
    # Destination header is an absolute URL
    move = nc.find("MOVE", "")[0]
    assert move.headers["Destination"] == f"https://nc.example{FILES}/dst.txt"
    assert move.headers["Overwrite"] == "T"


def test_move_plain_success(nc, call):
    def h(req):
        if req.method == "MOVE":
            return httpx.Response(201)
        if req.method == "PROPFIND":
            return multistatus([(req.url.path, "<d:resourcetype/>")])
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_move", {"source": "/a", "destination": "/b"})
    assert res["ok"] and res["fallback"] is False


def test_delete_verifies_404(nc, call):
    state = {f"{FILES}/old.txt": b"x"}

    def h(req):
        p = req.url.path.rstrip("/")
        if req.method == "DELETE":
            state.pop(p, None)
            return httpx.Response(204)
        if req.method == "PROPFIND":
            return multistatus([(req.url.path, "<d:resourcetype/>")]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_delete", {"path": "/old.txt"})
    assert res["ok"] and res["verified"] is True and f"{FILES}/old.txt" not in state


def test_delete_still_present_fails(nc, call):
    def h(req):
        if req.method == "DELETE":
            return httpx.Response(204)
        if req.method == "PROPFIND":
            return multistatus([(req.url.path, "<d:resourcetype/>")])  # never 404
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_delete", {"path": "/old.txt"})
    assert res["ok"] is False


def test_mkdir_verified(nc, call):
    state = set()

    def h(req):
        p = req.url.path.rstrip("/")
        if req.method == "MKCOL":
            state.add(p)
            return httpx.Response(201)
        if req.method == "PROPFIND":
            return multistatus([(req.url.path, "<d:resourcetype><d:collection/></d:resourcetype>")]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_file_mkdir", {"path": "/NewDir"})
    assert res["ok"] and res["verified"] is True
