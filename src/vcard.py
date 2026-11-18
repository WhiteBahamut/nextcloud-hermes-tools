"""Minimal vCard 4.0 support.

- Continuation lines (leading space/tab) are unfolded BEFORE parsing.
- Some servers wrap the vCard in CDATA — stripped.
- Group prefixes (``item1.EMAIL:...``) are normalized away.
- :func:`build_vcard` emits vCard 4.0 with required FN and UID=uuid4; bodies are UTF-8.
"""

from __future__ import annotations

import re
import uuid

from .ical import esc, fold, parse_content_line as _parse_content_line, unfold


def strip_cdata(text: str) -> str:
    return re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text or "", flags=re.S)


def parse_content_line(line: str):
    """``NAME;PARAM=V:value`` -> (NAME, params, value); group prefix stripped."""
    return _parse_content_line(line, strip_group=True)


def parse_vcard(text: str) -> dict:
    """vCard text -> {uid, fn, emails[], phones[], org, note, raw}."""
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
        "raw": text,
    }


def build_vcard(fn, email="", phone="", org="", note="", uid=None) -> str:
    """Build a vCard 4.0 string (FN required, UID=uuid4). ``email``/``phone`` accept a str or list[str]; '' / [] emit none."""
    uid = uid or str(uuid.uuid4())
    emails = [email] if isinstance(email, str) and email else [e for e in (email or []) if e]
    phones = [phone] if isinstance(phone, str) and phone else [p for p in (phone or []) if p]
    lines = ["BEGIN:VCARD", "VERSION:4.0", f"UID:{uid}", f"FN:{esc(fn)}"]
    for e in emails:
        lines.append(f"EMAIL;TYPE=HOME:{esc(e)}")
    for p in phones:
        lines.append(f"TEL;TYPE=CELL:{esc(p)}")
    if org:
        lines.append(f"ORG:{esc(org)}")
    if note:
        lines.append(f"NOTE:{esc(note)}")
    lines.append("END:VCARD")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
