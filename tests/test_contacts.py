"""Contacts handlers: create/edit/search/list with read-back verification."""

import httpx
from conftest import BOOK_DAV, multistatus


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
    body = state[f"{BOOK_DAV}/{res['uid']}.vcf"]
    assert "FN:Müller\\, Jörg" in body and "EMAIL" in body and f"UID:{res['uid']}" in body


def _contact_edit_handler(state, stored):
    def h(req):
        p = req.url.path
        if req.method == "PROPFIND":
            return multistatus([
                (f"{BOOK_DAV}/", '<d:resourcetype><d:collection/></d:resourcetype>'),
                (f"{BOOK_DAV}/c1.vcf", f'<d:getetag>&quot;e1&quot;</d:getetag><card:address-data>{stored}</card:address-data>'),
            ])
        if req.method == "PUT":
            state[p] = req.content.decode("utf-8")
            return httpx.Response(204)
        if req.method == "GET":
            return httpx.Response(200, text=state.get(p, stored))
        return httpx.Response(404, text="nf")
    return h


VC_C1 = (
    "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:Alice\r\n"
    "EMAIL;TYPE=HOME:old@x.de\r\nTEL;TYPE=CELL:+1\r\nORG:OldOrg\r\nEND:VCARD\r\n"
)


def test_contact_edit_email_list_replaces_multivalue(nc, call):
    state = {}
    nc.handler = _contact_edit_handler(state, VC_C1)
    res = call("nc_contact_edit", {"book": "contacts", "uid": "c1", "email": ["a@x.de", "b@x.de"], "phone": ["+1", "+2"]})
    assert res["ok"] and res["verified"]
    methods = [r.method for r in nc.requests]
    assert methods == ["PROPFIND", "PUT", "GET"]  # find -> PUT -> read-back
    put = nc.requests[1]
    assert put.headers.get("If-Match") == '"e1"'
    assert "text/vcard" in put.headers.get("Content-Type", "")
    body = state[f"{BOOK_DAV}/c1.vcf"]
    assert "EMAIL;TYPE=HOME:a@x.de" in body and "EMAIL;TYPE=HOME:b@x.de" in body
    assert "TEL;TYPE=CELL:+1" in body and "TEL;TYPE=CELL:+2" in body
    assert "old@x.de" not in body
    assert "ORG:OldOrg" in body  # untouched field preserved


def test_contact_edit_empty_string_clears_field(nc, call):
    state = {}
    nc.handler = _contact_edit_handler(state, VC_C1)
    res = call("nc_contact_edit", {"book": "contacts", "uid": "c1", "email": ""})
    assert res["ok"] and res["verified"]
    body = state[f"{BOOK_DAV}/c1.vcf"]
    assert "EMAIL" not in body


def test_contact_edit_readback_mismatch_fails(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "PROPFIND":
            return multistatus([
                (f"{BOOK_DAV}/", '<d:resourcetype><d:collection/></d:resourcetype>'),
                (f"{BOOK_DAV}/c1.vcf", f'<d:getetag>&quot;e1&quot;</d:getetag><card:address-data>{VC_C1}</card:address-data>'),
            ])
        if req.method == "PUT":
            state[p] = req.content.decode("utf-8")
            return httpx.Response(204)
        if req.method == "GET":
            tampered = state[p].replace("a@x.de", "evil@x.de")
            return httpx.Response(200, text=tampered)
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_contact_edit", {"book": "contacts", "uid": "c1", "email": ["a@x.de"]})
    assert res["ok"] is False and "edit verification failed" in res["error"]


def test_contact_search_local_filter(nc):
    import conftest

    _ctx, call = conftest.make_caller()
    vc1 = "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:Alice Example\r\nEMAIL;TYPE=HOME:alice@x.de\r\nEND:VCARD\r\n"
    vc2 = "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c2\r\nFN:Bob\r\nTEL:+49 30 555\r\nEND:VCARD\r\n"

    def h(req):
        return multistatus([
            (f"{BOOK_DAV}/", '<d:resourcetype><d:collection/></d:resourcetype>'),
            (f"{BOOK_DAV}/c1.vcf", f"<card:address-data>{vc1}</card:address-data>"),
            (f"{BOOK_DAV}/c2.vcf", f"<card:address-data>{vc2}</card:address-data>"),
        ])

    nc.handler = h
    res = call("nc_contact_search", {"book": "contacts", "term": "ALICE"})
    assert res["ok"] and [c["uid"] for c in res["contacts"]] == ["c1"]
    res = call("nc_contact_search", {"book": "contacts", "term": "555"})  # phone substring
    assert [c["uid"] for c in res["contacts"]] == ["c2"]


def test_contact_list_books_home_propfind(nc, call):
    home = "/remote.php/dav/addressbooks/users/bot"

    def h(req):
        assert req.method == "PROPFIND" and req.url.path == home + "/"
        assert req.headers["Depth"] == "1"
        return multistatus([
            (f"{home}/", '<d:resourcetype><d:collection/></d:resourcetype>'),
            (f"{home}/contacts", '<d:resourcetype><d:collection/></d:resourcetype><d:displayname>Contacts</d:displayname>'),
            (f"{home}/work", '<d:resourcetype><d:collection/></d:resourcetype><d:displayname>Work</d:displayname>'),
        ])

    nc.handler = h
    res = call("nc_contact_list_books", {})
    assert res["ok"] and res["count"] == 2
    assert [r.method for r in nc.requests] == ["PROPFIND"]
    assert res["books"] == [{"name": "contacts", "display_name": "Contacts"},
                            {"name": "work", "display_name": "Work"}]
