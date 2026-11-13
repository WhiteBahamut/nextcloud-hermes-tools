"""Contacts tools — CardDAV under ``/remote.php/dav/addressbooks/users/<user>/<book>/``.

- List via PROPFIND Depth 1 (``card:address-data``), CDATA stripped and lines
  unfolded before parsing.
- Search filters locally on the parsed list (fn/email/phone substring,
  case-insensitive).
- Edits PUT with ``If-Match`` (etag unescaped) and verify by read-back.
  Non-ASCII names are preserved (UTF-8 bodies).
"""

from __future__ import annotations

import html
import uuid
from urllib.parse import unquote

from . import client, schemas, vcard
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
    client.require(
        client.request("PUT", href, content=body.encode("utf-8"),
                       headers={"Content-Type": "text/vcard; charset=utf-8"}),
        (200, 201, 204),
    )
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got:
        return client.err(f"create verification failed: UID {uid} not in read-back", book=book, uid=uid)
    return client.ok(book=book, uid=uid, verified=True)


def _edit(args):
    book = args.get("book") or "contacts"
    uid = args["uid"]
    href, etag, card = _find(book, uid)
    body = vcard.build_vcard(
        fn=args.get("fn") or card.get("fn") or "",
        email=args.get("email") or (card.get("emails") or [""])[0],
        phone=args.get("phone") or (card.get("phones") or [""])[0],
        org=args.get("org") if "org" in args else card.get("org", ""),
        note=args.get("note") if "note" in args else card.get("note", ""),
        uid=uid,
    )
    client.require(
        client.request("PUT", href, content=body.encode("utf-8"),
                       headers={"Content-Type": "text/vcard; charset=utf-8", "If-Match": etag}),
        (200, 201, 204),
    )
    got = client.dav_get(href).text
    if f"UID:{uid}" not in got:
        return client.err(f"edit verification failed: UID {uid} not in read-back", book=book, uid=uid)
    return client.ok(book=book, uid=uid, verified=True)


TOOLS = [
    ("nc_contact_list", schemas.NC_CONTACT_LIST, client.tool(_list)),
    ("nc_contact_search", schemas.NC_CONTACT_SEARCH, client.tool(_search)),
    ("nc_contact_get", schemas.NC_CONTACT_GET, client.tool(_get)),
    ("nc_contact_create", schemas.NC_CONTACT_CREATE, client.tool(_create)),
    ("nc_contact_edit", schemas.NC_CONTACT_EDIT, client.tool(_edit)),
]
