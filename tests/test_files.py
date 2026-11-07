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
    assert nc.requests[0].headers["Depth"] == "1"  # explicit Depth
    by_name = {e["name"]: e for e in res["entries"]}
    assert set(by_name) == {"Docs", "a b.txt"}  # href URL-decoded
    assert by_name["Docs"]["is_dir"] is True
    f = by_name["a b.txt"]
    assert f["is_dir"] is False and f["size"] == 5 and f["content_type"] == "text/plain" and f["etag"] == '"e1"'


def test_file_list_invalid_depth(nc, call):
    res = call("nc_file_list", {"path": "/", "depth": "2"})
    assert res["ok"] is False


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
