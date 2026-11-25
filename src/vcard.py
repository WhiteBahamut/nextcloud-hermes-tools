"""Minimal vCard 4.0 support.

- Continuation lines (leading space/tab) are unfolded BEFORE parsing.
- Some servers wrap the vCard in CDATA — stripped.
- Group prefixes (``item1.EMAIL:...``) are normalized away.
- :func:`build_vcard` emits vCard 4.0 with required FN and UID=uuid4; bodies are UTF-8.
"""

from __future__ import annotations

import re
import uuid

from .ical import esc, fold, parse_content_line as _parse_content_line, unfold, unesc

# RFC 6350 ADR value components, in order: pobox;extended;street;locality;region;postal;country
ADR_KEYS = ("pobox", "extended", "street", "city", "region", "postal", "country")


def strip_cdata(text: str) -> str:
    return re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text or "", flags=re.S)


def split_unescaped(value: str, sep: str = ";") -> list:
    """Split on ``sep`` unless it is escaped by a backslash; escape pairs stay intact in the parts."""
    parts, cur, i = [], [], 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            cur.append(value[i : i + 2])
            i += 2
            continue
        if ch == sep:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def parse_adr(value: str) -> dict:
    """ADR value -> dict keyed by :data:`ADR_KEYS` (``city`` = RFC 'locality').

    Components are mapped by index (positional meaning is kept even when leading
    components are empty); empty components are skipped and vCard escapes
    (``\\;`` ``\\,`` ``\\n`` ``\\\\``) are undone after splitting.
    """
    parts = split_unescaped(value or "", ";")
    addr = {}
    for i, key in enumerate(ADR_KEYS):
        if i < len(parts):
            v = unesc(parts[i])
            if v:
                addr[key] = v
    return addr


def normalize_address(address) -> dict:
    """User-supplied address dict -> canonical form: known keys only, values str() and non-empty."""
    if not isinstance(address, dict):
        return {}
    out = {}
    for key in ADR_KEYS:
        v = address.get(key)
        if v is None and key == "city":
            v = address.get("locality")  # RFC name for the locality component
        if v:
            out[key] = str(v)
    return out


def adr_value(address: dict) -> str:
    """Address dict -> ADR value with all 7 components, each escaped via :func:`ical.esc`."""
    return ";".join(esc(address.get(k) or "") for k in ADR_KEYS)


def parse_content_line(line: str):
    """``NAME;PARAM=V:value`` -> (NAME, params, value); group prefix stripped."""
    return _parse_content_line(line, strip_group=True)


def parse_vcard(text: str) -> dict:
    """vCard text -> {uid, fn, emails[], phones[], org, note, addresses[], raw}.

    ``addresses`` is a list of ADR dicts (see :func:`parse_adr`); empty/absent ADR
    yields ``[]``. Other fields keep their raw (still escaped) values.
    """
    text = strip_cdata(text or "")
    props = {}
    for line in unfold(text):
        if not line.strip():
            continue
        name, params, value = parse_content_line(line)
        if name in ("BEGIN", "END", "VERSION"):
            continue
        props.setdefault(name, []).append((params, value))

    def first(n):
        return props[n][0][1] if props.get(n) else ""

    def all_(n):
        return [v for _, v in props.get(n, [])]

    return {
        "uid": first("UID"),
        "fn": first("FN"),
        "emails": all_("EMAIL"),
        "phones": all_("TEL"),
        "org": ";".join(all_("ORG")),
        "note": first("NOTE"),
        "addresses": [a for a in (parse_adr(v) for v in all_("ADR")) if a],
        "raw": text,
    }


def build_vcard(fn, email="", phone="", org="", note="", uid=None, addresses=None) -> str:
    """Build a vCard 4.0 string (FN required, UID=uuid4). ``email``/``phone`` accept a str or list[str]; '' / [] emit none. ``addresses`` accepts one address dict or a list of dicts (see :func:`normalize_address`); each is emitted as ``ADR;TYPE=HOME`` with every component escaped."""
    uid = uid or str(uuid.uuid4())
    emails = [email] if isinstance(email, str) and email else [e for e in (email or []) if e]
    phones = [phone] if isinstance(phone, str) and phone else [p for p in (phone or []) if p]
    addrs = [a for a in (normalize_address(x) for x in (addresses if isinstance(addresses, list) else [addresses])) if a]
    lines = ["BEGIN:VCARD", "VERSION:4.0", f"UID:{uid}", f"FN:{esc(fn)}"]
    for e in emails:
        lines.append(f"EMAIL;TYPE=HOME:{esc(e)}")
    for p in phones:
        lines.append(f"TEL;TYPE=CELL:{esc(p)}")
    for a in addrs:
        lines.append(f"ADR;TYPE=HOME:{adr_value(a)}")
    if org:
        lines.append(f"ORG:{esc(org)}")
    if note:
        lines.append(f"NOTE:{esc(note)}")
    lines.append("END:VCARD")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
