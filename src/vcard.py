"""Minimal vCard 4.0 support.

- Continuation lines (leading space/tab) are unfolded BEFORE parsing.
- Some servers wrap the vCard in CDATA — stripped.
- Group prefixes (``item1.EMAIL:...``) are normalized away.
- :func:`build_vcard` emits vCard 4.0 with required FN and UID=uuid4; bodies are UTF-8.
"""

from __future__ import annotations

import re
import uuid

from .ical import esc, fold, unfold


def strip_cdata(text: str) -> str:
    return re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", text or "", flags=re.S)


def parse_content_line(line: str):
    """``NAME;PARAM=V:value`` -> (NAME, params, value); group prefix stripped."""
    in_quote = False
    idx = -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == ":" and not in_quote:
            idx = i
            break
    if idx < 0:
        return line.upper(), {}, ""
    head, value = line[:idx], line[idx + 1:]
    parts = head.split(";")
    name = parts[0].upper()
    if "." in name:
        name = name.split(".", 1)[1]
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return name, params, value


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
    """Build a vCard 4.0 string (FN required, UID=uuid4)."""
    uid = uid or str(uuid.uuid4())
    lines = ["BEGIN:VCARD", "VERSION:4.0", f"UID:{uid}", f"FN:{esc(fn)}"]
    if email:
        lines.append(f"EMAIL;TYPE=HOME:{esc(email)}")
    if phone:
        lines.append(f"TEL;TYPE=CELL:{esc(phone)}")
    if org:
        lines.append(f"ORG:{esc(org)}")
    if note:
        lines.append(f"NOTE:{esc(note)}")
    lines.append("END:VCARD")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
