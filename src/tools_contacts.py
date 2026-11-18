"""Contacts tools — CardDAV under ``/remote.php/dav/addressbooks/users/<user>/<book>/``.

- List via PROPFIND Depth 1 (``card:address-data``), CDATA stripped and lines
  unfolded before parsing. ``nc_contact_list_books`` lists the addressbook home:
  PROPFIND Depth 1 on ``/remote.php/dav/addressbooks/users/<user>/`` with
  ``resourcetype`` + ``displayname``.
- Search filters locally on the parsed list (fn/email/phone substring,
  case-insensitive).
- Edits PUT with ``If-Match`` (etag unescaped) and verify by read-back.
  Non-ASCII names are preserved (UTF-8 bodies).
"""

from __future__ import annotations

import html
import uuid
from urllib.parse import unquote

from . import client, dav, schemas, vcard
from .dav import PROPFIND_ALL, parse_multistatus


def _book_href(book):
    return client.book_dav(book)


def _summarize(card: dict) -> dict:
    return {
        "uid": card.get("uid", ""),
        "fn": card.get("fn", ""),
        "emails": card.get("emails", []),
        "phones": card.get("phones", []),
        "org": card.get("org", ""),
    }


def _iter_cards(book):
    """Yield (href, etag, parsed_card) for every contact in the book."""
    href = _book_href(book)
    resp = client.propfind(href, depth=1, body=PROPFIND_ALL)
    target = href.rstrip("/")
    for r in parse_multistatus(resp.text):
        rhref = unquote(r["href"]).rstrip("/")
        if rhref == target:
            continue
        data = r["props"].get("address-data") or ""
        card = vcard.parse_vcard(data) if data else {"uid": rhref.rsplit("/", 1)[-1]}
        etag = html.unescape(r["props"].get("getetag") or "")
        yield rhref, etag, card


def _find(book, uid):
    for rhref, etag, card in _iter_cards(book):
        entry_uid = card.get("uid") or rhref.rsplit("/", 1)[-1].removesuffix(".vcf")
        if entry_uid == uid or rhref.endswith(f"/{uid}.vcf"):
            return rhref, etag, card
    raise client.NcError(404, f"no contact with UID {uid} in book {book}")


def _list(args):
    book = args.get("book") or "contacts"
    limit = int(args.get("limit") or 500)
    out = []
    for _href, _etag, card in _iter_cards(book):
        out.append(_summarize(card))
        if len(out) >= limit:
            break
    return client.ok(book=book, count=len(out), contacts=out)


def _search(args):
    book = args.get("book") or "contacts"
    term = (args.get("term") or "").lower()
    if not term:
        return client.err("empty search term")
    out = []
    for _href, _etag, card in _iter_cards(book):
        hay = " ".join([card.get("fn", ""), *card.get("emails", []), *card.get("phones", []), card.get("org", "")]).lower()
        if term in hay:
            out.append(_summarize(card))
    return client.ok(book=book, term=term, count=len(out), contacts=out)


def _get(args):
    book = args.get("book") or "contacts"
    uid = args["uid"]
    href, _etag, card = _find(book, uid)
    full = vcard.parse_vcard(client.dav_get(href).text)
    result = _summarize(full)
    result["note"] = full.get("note", "")
    return client.ok(book=book, **result)


def _create(args):
    book = args.get("book") or "contacts"
    fn = args.get("fn") or ""
    if not fn:
        return client.err("fn (full name) required")
    uid = str(uuid.uuid4())
    body = vcard.build_vcard(
        fn=fn, email=args.get("email") or "", phone=args.get("phone") or "",
        org=args.get("org") or "", note=args.get("note") or "", uid=uid,
    )
    href = _book_href(book) + uid + ".vcf"
    client.dav_put(href, body.encode("utf-8"), "text/vcard; charset=utf-8")
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got:
        return client.err(f"create verification failed: UID {uid} not in read-back", book=book, uid=uid)
    return client.ok(book=book, uid=uid, verified=True)


def _as_list(v):
    """''/None/[] -> []; str -> [v]; else list(v)."""
    if v is None or v == "" or v == []:
        return []
    return [v] if isinstance(v, str) else [x for x in v if x]


def _edit(args):
    book = args.get("book") or "contacts"
    uid = args["uid"]
    href, etag, card = _find(book, uid)
    emails = _as_list(args["email"]) if "email" in args else (card.get("emails") or [])
    phones = _as_list(args["phone"]) if "phone" in args else (card.get("phones") or [])
    org = args.get("org") if "org" in args else card.get("org", "")
    note = args.get("note") if "note" in args else card.get("note", "")
    fn = args.get("fn") or card.get("fn") or ""
    body = vcard.build_vcard(fn=fn, email=emails, phone=phones, org=org, note=note, uid=uid)
    client.dav_put(href, body.encode("utf-8"), "text/vcard; charset=utf-8", etag=etag)
    got = vcard.parse_vcard(client.dav_get(href).text)
    esc = vcard.esc
    expected = {
        "uid": uid,
        "fn": esc(fn),
        "emails": [esc(e) for e in emails],
        "phones": [esc(p) for p in phones],
        "org": esc(org) if org else "",
        "note": esc(note),
    }
    if "email" not in args:
        expected["emails"] = got.get("emails")  # unchanged field: skip comparison
    if "phone" not in args:
        expected["phones"] = got.get("phones")
    if "org" not in args:
        expected["org"] = got.get("org", "")
    if "note" not in args:
        expected["note"] = got.get("note", "")
    if "fn" not in args or not args.get("fn"):
        expected["fn"] = got.get("fn", "")
    problems = [f"{k}: got {got.get(k)!r} != {v!r}" for k, v in expected.items() if got.get(k) != v]
    if problems:
        return client.err("edit verification failed: " + "; ".join(problems), book=book, uid=uid)
    return client.ok(book=book, uid=uid, verified=True)


def _book_list(args):
    """PROPFIND Depth 1 on the addressbook home -> DAV dir name + display name per address book."""
    books = dav.list_collections(client.book_home())
    return client.ok(count=len(books), books=books)


TOOLS = [
    ("nc_contact_list", schemas.NC_CONTACT_LIST, client.tool(_list)),
    ("nc_contact_list_books", schemas.NC_CONTACT_LIST_BOOKS, client.tool(_book_list)),
    ("nc_contact_search", schemas.NC_CONTACT_SEARCH, client.tool(_search)),
    ("nc_contact_get", schemas.NC_CONTACT_GET, client.tool(_get)),
    ("nc_contact_create", schemas.NC_CONTACT_CREATE, client.tool(_create)),
    ("nc_contact_edit", schemas.NC_CONTACT_EDIT, client.tool(_edit)),
]
