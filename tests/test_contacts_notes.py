import httpx
from conftest import multistatus
from nextcloud_tools import vcard

BOOK = "/remote.php/dav/addressbooks/bot/contacts"
FILES = "/remote.php/dav/files/bot"
NOTES_API = "/index.php/apps/notes/api/v1/notes"


# --- vcard.py ------------------------------------------------------------------------


def test_vcard_unfold_cdata_group_prefix():
    raw = (
        "<![CDATA[BEGIN:VCARD\r\nVERSION:4.0\r\nUID:u9\r\nFN:J\xc3\xb6rg M\xc3\xbcller\r\n"
        "item1.EMAIL:a@b.c\r\nTEL;TYPE=CELL:+49 30\r\nORG:Acme\\;HQ\r\nEND:VCARD]]>"
    ).encode("latin-1").decode("utf-8")
    card = vcard.parse_vcard(raw)
    assert card["uid"] == "u9"
    assert card["emails"] == ["a@b.c"]  # group prefix item1. normalized away
    assert card["phones"] == ["+49 30"]
    assert card["org"] == "Acme\\;HQ"


def test_vcard_folded_line_unfolds():
    raw = "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:u\r\nFN:Very Long Name That Was Fold\r\n ed Across Lines\r\nEND:VCARD\r\n"
    card = vcard.parse_vcard(raw)
    assert card["fn"] == "Very Long Name That Was Folded Across Lines"


def test_build_vcard_roundtrip_utf8():
    text = vcard.build_vcard(fn="Müller, Jörg", email="j@x.de", phone="+49", uid="u1")
    card = vcard.parse_vcard(text)
    assert card["fn"] == "Müller\\, Jörg"  # escaped on build; non-ASCII preserved as UTF-8
    assert card["uid"] == "u1" and card["emails"] == ["j@x.de"]
    assert "VERSION:4.0" in text and "FN:" in text


# --- contacts handlers -----------------------------------------------------------------


def test_contact_create_verified(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "PUT":
            state[p] = req.content.decode("utf-8")
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, text=state[p]) if p in state else httpx.Response(404, text="nf")
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_contact_create", {"book": "contacts", "fn": "Müller, Jörg", "email": "j@x.de", "phone": "+49"})
    assert res["ok"] and res["verified"]
    body = state[f"{BOOK}/{res['uid']}.vcf"]
    assert "FN:Müller\\, Jörg" in body and "EMAIL" in body and f"UID:{res['uid']}" in body


def test_contact_search_local_filter(nc):
    import conftest

    _ctx, call = conftest.make_caller()
    vc1 = "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:Alice Example\r\nEMAIL;TYPE=HOME:alice@x.de\r\nEND:VCARD\r\n"
    vc2 = "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c2\r\nFN:Bob\r\nTEL:+49 30 555\r\nEND:VCARD\r\n"

    def h(req):
        return multistatus([
            (f"{BOOK}/", '<d:resourcetype><d:collection/></d:resourcetype>'),
            (f"{BOOK}/c1.vcf", f"<card:address-data>{vc1}</card:address-data>"),
            (f"{BOOK}/c2.vcf", f"<card:address-data>{vc2}</card:address-data>"),
        ])

    nc.handler = h
    res = call("nc_contact_search", {"book": "contacts", "term": "ALICE"})
    assert res["ok"] and [c["uid"] for c in res["contacts"]] == ["c1"]
    res = call("nc_contact_search", {"book": "contacts", "term": "555"})  # phone substring
    assert [c["uid"] for c in res["contacts"]] == ["c2"]


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
    assert state[f"{FILES}/Notes/Shopping.txt"] == b"milk"
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
