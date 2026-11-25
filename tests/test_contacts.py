"""Contacts handlers: create/edit/search/list with read-back verification."""

import httpx
import pytest
from conftest import BOOK_DAV, multistatus
from nextcloud_tools import vcard


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


# --- postal addresses (ADR) ------------------------------------------------------------


def test_parse_vcard_single_adr():
    raw = (
        "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:Alice\r\n"
        "ADR;TYPE=HOME:;;Main St 1;Berlin;Berlin;10115;Germany\r\n"
        "END:VCARD\r\n"
    )
    card = vcard.parse_vcard(raw)
    assert card["addresses"] == [
        {"street": "Main St 1", "city": "Berlin", "region": "Berlin", "postal": "10115", "country": "Germany"}
    ]


def test_parse_vcard_multiple_adr_and_escapes():
    raw = (
        "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:Alice\r\n"
        "ADR;TYPE=HOME:;;Hauptstraße 5\\, 2. OG\\; Aufgang B;Berlin;;10115;Germany\r\n"
        "ADR;TYPE=WORK:PO 1;Suite 2;Workweg 3;Hamburg;HH;20095;Deutschland\r\n"
        "ADR:;;Line1\\nLine2;Town;;;\r\n"
        "END:VCARD\r\n"
    )
    card = vcard.parse_vcard(raw)
    assert len(card["addresses"]) == 3
    home, work, third = card["addresses"]
    assert home["street"] == "Hauptstraße 5, 2. OG; Aufgang B"  # \, and \; unescaped after splitting; non-ASCII kept
    assert home["city"] == "Berlin" and home["postal"] == "10115"
    assert work == {"pobox": "PO 1", "extended": "Suite 2", "street": "Workweg 3",
                    "city": "Hamburg", "region": "HH", "postal": "20095", "country": "Deutschland"}
    assert third == {"street": "Line1\nLine2", "city": "Town"}  # \n unescaped; trailing empties skipped


def test_parse_vcard_missing_or_empty_adr():
    card = vcard.parse_vcard("BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:A\r\nEND:VCARD\r\n")
    assert card["addresses"] == []  # not None
    card = vcard.parse_vcard("BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:A\r\nADR;TYPE=HOME:;;;;;;\r\nEND:VCARD\r\n")
    assert card["addresses"] == []


def test_parse_vcard_vcard30_adr():
    # Nextcloud/sabre-dav converts cards to vCard 3.0 on GET when the Accept header
    # matches no vcard type (our client sends Accept: application/json) — ADR has the
    # same 7-component structure and escaping in 3.0 (RFC 2426 3.3.1), so it must parse.
    raw = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:c1\r\nFN:Alice\r\n"
        "ADR;TYPE=HOME:;;Main St 1;Berlin;;10115;Germany\r\n"
        "ADR;TYPE=WORK:PO 9;;Workweg 3;Hamburg;HH;20095;\r\nEND:VCARD\r\n"
    )
    card = vcard.parse_vcard(raw)
    assert card["addresses"] == [
        {"street": "Main St 1", "city": "Berlin", "postal": "10115", "country": "Germany"},
        {"pobox": "PO 9", "street": "Workweg 3", "city": "Hamburg", "region": "HH", "postal": "20095"},
    ]


def test_parse_vcard_adr_folded_and_cdata():
    raw = (
        "<![CDATA[BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:A\r\n"
        "ADR;TYPE=HOME:;;A Very Long Street Name That Keeps Going And Go\r\n"
        " ing Past The Fold Limit;Berlin;;10115;Germany\r\nEND:VCARD]]>"
    )
    card = vcard.parse_vcard(raw)
    assert card["addresses"] == [
        {"street": "A Very Long Street Name That Keeps Going And Going Past The Fold Limit",
         "city": "Berlin", "postal": "10115", "country": "Germany"}
    ]


def test_build_vcard_address_roundtrip():
    addr = {"street": "Main St 1; Apt 2", "city": "Berlin", "postal": "10115", "country": "Deutsch,land"}
    text = vcard.build_vcard(fn="Alice", uid="c1", addresses=[addr])
    assert "ADR;TYPE=HOME:;;Main St 1\\; Apt 2;Berlin;;10115;Deutsch\\,land" in text  # esc() per component
    card = vcard.parse_vcard(text)
    assert card["addresses"] == [{"street": "Main St 1; Apt 2", "city": "Berlin", "postal": "10115", "country": "Deutsch,land"}]
    # a single dict is accepted too, and no address emits no ADR line
    assert vcard.parse_vcard(vcard.build_vcard(fn="A", uid="c2", addresses=addr))["addresses"] == card["addresses"]
    assert "ADR" not in vcard.build_vcard(fn="A", uid="c3")


def test_build_vcard_long_address_folds_and_roundtrips():
    addr = {"street": "S" * 90 + ", corner", "city": "Berlin"}
    text = vcard.build_vcard(fn="A", uid="c1", addresses=[addr])
    assert all(len(l.encode()) <= 75 or l.startswith(" ") for l in text.split("\r\n"))  # folded like other lines
    assert vcard.parse_vcard(text)["addresses"] == [{"street": "S" * 90 + ", corner", "city": "Berlin"}]


def test_contact_list_and_search_include_addresses(nc, call):
    vc1 = (
        "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:Alice Example\r\n"
        "ADR;TYPE=HOME:;;Main St 1;Berlin;;10115;Germany\r\nEND:VCARD\r\n"
    )
    vc2 = "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c2\r\nFN:Bob\r\nEND:VCARD\r\n"

    def h(req):
        return multistatus([
            (f"{BOOK_DAV}/", '<d:resourcetype><d:collection/></d:resourcetype>'),
            (f"{BOOK_DAV}/c1.vcf", f"<card:address-data>{vc1}</card:address-data>"),
            (f"{BOOK_DAV}/c2.vcf", f"<card:address-data>{vc2}</card:address-data>"),
        ])

    nc.handler = h
    res = call("nc_contact_list", {"book": "contacts"})
    by_uid = {c["uid"]: c for c in res["contacts"]}
    assert by_uid["c1"]["addresses"] == [{"street": "Main St 1", "city": "Berlin", "postal": "10115", "country": "Germany"}]
    assert by_uid["c2"]["addresses"] == []
    res = call("nc_contact_search", {"book": "contacts", "term": "alice"})
    assert res["contacts"][0]["addresses"] == by_uid["c1"]["addresses"]


def test_contact_get_includes_addresses(nc, call):
    vc = (
        "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:Alice\r\nNOTE:hi\r\n"
        "ADR;TYPE=HOME:;;Altweg 9;Bonn;NRW;53113;Deutschland\r\nEND:VCARD\r\n"
    )

    def h(req):
        if req.method == "PROPFIND":
            return multistatus([
                (f"{BOOK_DAV}/", '<d:resourcetype><d:collection/></d:resourcetype>'),
                (f"{BOOK_DAV}/c1.vcf", f"<card:address-data>{vc}</card:address-data>"),
            ])
        if req.method == "GET":
            return httpx.Response(200, text=vc)
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_contact_get", {"book": "contacts", "uid": "c1"})
    assert res["ok"] and res["note"] == "hi"
    assert res["addresses"] == [{"street": "Altweg 9", "city": "Bonn", "region": "NRW", "postal": "53113", "country": "Deutschland"}]


def test_contact_create_with_address_verified(nc, call):
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
    res = call("nc_contact_create", {
        "book": "contacts", "fn": "Müller, Jörg",
        "address": {"street": "Main St 1", "city": "Berlin", "region": "", "postal": "10115", "country": "Germany"},
    })
    assert res["ok"] and res["verified"]
    body = state[f"{BOOK_DAV}/{res['uid']}.vcf"]
    assert "ADR;TYPE=HOME:;;Main St 1;Berlin;;10115;Germany" in body  # empty region dropped, non-ASCII fn intact
    assert "FN:Müller\\, Jörg" in body


VC_C1_ADR = (
    "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:c1\r\nFN:Alice\r\n"
    "ADR;TYPE=HOME:;;Altweg 9;Bonn;NRW;53113;Deutschland\r\nEND:VCARD\r\n"
)


def test_contact_edit_address_set_verified(nc, call):
    state = {}
    nc.handler = _contact_edit_handler(state, VC_C1)  # stored card has no ADR
    res = call("nc_contact_edit", {
        "book": "contacts", "uid": "c1",
        "address": {"street": "Main St 1", "city": "Berlin", "postal": "10115", "country": "Germany"},
    })
    assert res["ok"] and res["verified"]
    assert [r.method for r in nc.requests] == ["PROPFIND", "PUT", "GET"]  # find -> PUT -> read-back
    body = state[f"{BOOK_DAV}/c1.vcf"]
    assert "ADR;TYPE=HOME:;;Main St 1;Berlin;;10115;Germany" in body


def test_contact_edit_address_list_replaces(nc, call):
    state = {}
    nc.handler = _contact_edit_handler(state, VC_C1_ADR)
    res = call("nc_contact_edit", {
        "book": "contacts", "uid": "c1",
        "address": [{"city": "Berlin"}, {"city": "Hamburg", "country": "DE"}],
    })
    assert res["ok"] and res["verified"]
    body = state[f"{BOOK_DAV}/c1.vcf"]
    assert body.count("ADR;TYPE=HOME:") == 2
    assert "ADR;TYPE=HOME:;;;Berlin;;;" in body  # city-only address: 3 empty components before city
    assert "Altweg 9" not in body


def test_contact_edit_address_cleared(nc, call):
    state = {}
    nc.handler = _contact_edit_handler(state, VC_C1_ADR)
    res = call("nc_contact_edit", {"book": "contacts", "uid": "c1", "address": ""})
    assert res["ok"] and res["verified"]
    assert "ADR" not in state[f"{BOOK_DAV}/c1.vcf"]
    res = call("nc_contact_edit", {"book": "contacts", "uid": "c1", "address": []})
    assert res["ok"] and res["verified"]


def test_contact_edit_address_unchanged_when_omitted(nc, call):
    state = {}
    nc.handler = _contact_edit_handler(state, VC_C1_ADR)
    res = call("nc_contact_edit", {"book": "contacts", "uid": "c1", "email": "a@x.de"})
    assert res["ok"] and res["verified"]
    body = state[f"{BOOK_DAV}/c1.vcf"]
    assert "ADR;TYPE=HOME:;;Altweg 9;Bonn;NRW;53113;Deutschland" in body  # untouched field preserved


def test_contact_edit_address_readback_mismatch_fails(nc, call):
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
            return httpx.Response(200, text=state[p].replace("Main St 1", "Evil St 9"))
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_contact_edit", {"book": "contacts", "uid": "c1", "address": {"street": "Main St 1", "city": "Berlin"}})
    assert res["ok"] is False and "edit verification failed" in res["error"] and "addresses" in res["error"]


def test_contact_create_address_readback_mismatch_fails(nc, call):
    state = {}

    def h(req):
        p = req.url.path
        if req.method == "PUT":
            state[p] = req.content.decode("utf-8")
            return httpx.Response(201)
        if req.method == "GET":
            # tampered read-back: the stored ADR comes back with a different street
            return httpx.Response(200, text=state[p].replace("Main St 1", "Evil St 9"))
        return httpx.Response(404, text="nf")

    nc.handler = h
    res = call("nc_contact_create", {"fn": "A", "address": {"street": "Main St 1", "city": "Berlin"}})
    assert res["ok"] is False and "create verification failed" in res["error"] and "addresses" in res["error"]


@pytest.mark.parametrize("tool,args,expect_propfind", [
    ("nc_contact_create", {"fn": "A", "address": "Berlin"}, False),
    ("nc_contact_create", {"fn": "A", "address": ["Berlin"]}, False),  # non-dict entry
    ("nc_contact_create", {"fn": "A", "address": {"foo": "bar"}}, False),  # no known keys -> would clear
    ("nc_contact_create", {"fn": "A", "address": 123}, False),  # non-iterable scalar
    ("nc_contact_edit", {"uid": "c1", "address": "Berlin"}, True),  # edit resolves the card first
    ("nc_contact_edit", {"uid": "c1", "address": ["Berlin"]}, True),
])
def test_contact_address_non_empty_string_rejected(nc, call, tool, args, expect_propfind):
    # the schema allows strings only as the '' clear sentinel; a non-empty string
    # must be rejected, never silently treated as "clear all addresses"
    state = {}
    nc.handler = _contact_edit_handler(state, VC_C1)
    res = call(tool, args)
    assert res["ok"] is False and res.get("status") == 400 and "address" in res["error"]
    assert nc.find("PUT", "") == []  # never written
    if expect_propfind:
        assert nc.methods() == ["PROPFIND"]
    else:
        assert nc.requests == []  # create rejects before any request


def test_build_vcard_escapes_cr_in_values():
    # a raw CR in a value must not inject a new content line into the card
    text = vcard.build_vcard(fn="A", uid="c1", note="line1\rNOTE:injected", addresses=[{"street": "X\rY"}])
    for line in text.split("\r\n"):
        assert "\r" not in line
    card = vcard.parse_vcard(text)
    assert card["note"] == "line1\\rNOTE:injected"  # non-ADR fields stay escaped on parse
    assert card["addresses"] == [{"street": "X\rY"}]  # ADR components are unescaped
