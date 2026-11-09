#!/usr/bin/env python3
"""Atomic, deduplicating append/count of session-review learnings (journal.md + AGENTS.md).

Stdlib-only. Two subcommands:

  append --file F --section "<heading>" [--threshold 0.5] [--min-shared 6]
      Reads candidate bullets from stdin, one per line. Every non-empty line
      MUST start with "- " (otherwise exit 2 and the file is untouched).
      Bullets matching prompt-injection / credential-exfiltration patterns or
      containing invisible Unicode are rejected: reported on stderr and in
      the JSON summary ONLY as {"reason", "len", "sha256"} — NEVER the bullet
      content, which may hold a secret the parser's redaction missed. Exit
      code stays 0 and nothing is appended for them. Each remaining bullet is
      deduplicated lexically (token Jaccard against ALL existing "- " bullet
      lines of the WHOLE file — never just the target section). Non-duplicates
      are inserted inside the section (before its end bound); if the section is
      absent it is created at EOF with a fixed intro line. The write is atomic
      (tmp file + os.replace). Prints a JSON summary {"added": [...],
      "duplicates": [...], "rejected": [...]} on stdout. On any error the tmp
      file is removed, a message goes to stderr, exit 1, and the original
      file is untouched.

  count --file F --section "<heading>"
      Prints the number of "- " bullet lines inside the section as a bare int.

  count --file F --all
      Prints the number of auto bullets file-wide: "- " lines ending in
      "(src: <8 hex>)" (SRC_BULLET_RE), regardless of section.

  verify
      Reads a unified diff on stdin and exits 0 iff every added/removed
      non-blank line is a complete single-line auto bullet (SRC_BULLET_RE:
      starts with "- " and ends with "(src: <8 hex>)") — no arbitrary line
      breaks (a hard-wrapped bullet fails), and no added "## " heading.
      Violations go to stderr, exit 1; prints "ok" when clean.
      Post-run gate for AGENTS.md: self-learning MUST NOT create chapters
      (e.g. "## Session-review", "## Session learnings …") or touch non-auto
      lines there.

Never raises out of main().
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

SECTION_INTRO = (
    "Raw queue of reviewed-session findings (`learnings.py append`: atomic write, lexical "
    "Jaccard dedupe against the whole file, injection/credential scan, dated bullets with "
    "`src:` provenance tags). Consolidation drains durable items into matching topical "
    "sections of AGENTS.md as undated auto bullets (`(src: …)`); this journal is bounded "
    "(JOURNAL_CAP) and rewritten by consolidation, never grown forever."
)

BULLET_RE = re.compile(r"^- ")
SRC_BULLET_RE = re.compile(r"^- .* \(src: [0-9a-f]{8}\)$")
TOKEN_RE = re.compile(r"[a-z0-9]+")

# Scan gate for appended bullets: invisible Unicode, prompt-injection phrasing,
# and credential-shaped content are rejected (Hermes-style entry scanning).
INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
INJECTION_RES = [
    re.compile(r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|original)\b.{0,40}\b(instructions?|rules?|guidelines?|prompts?)\b", re.IGNORECASE),
    re.compile(r"\b(system|developer)\s+prompt\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+(follow|obey|listen\s+to)\b", re.IGNORECASE),
    re.compile(r"\b(exfiltrat\w+|steal)\b.{0,40}\b(credentials?|secrets?|tokens?|passwords?|api[- ]?keys?)\b", re.IGNORECASE),
]
CRED_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[-_ ]?key|app[-_ ]?password)\s*[:=]\s*[\"']?[^\s\"']{6,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|bearer\s+[A-Za-z0-9._~+/=-]{20,}"
)


def scan_rejects(bullet: str) -> str | None:
    """Return a rejection reason if the bullet looks injected or credential-shaped, else None.

    Safety guidance that merely mentions secrets (e.g. "NEVER write secrets …")
    is allowed; only imperative injection phrasing and credential-shaped values
    (labeled assignments, private keys, bearer tokens) are rejected.
    """
    if INVISIBLE_RE.search(bullet):
        return "invisible unicode"
    for rx in INJECTION_RES:
        if rx.search(bullet):
            return "prompt-injection pattern"
    if CRED_RE.search(bullet):
        return "credential-shaped content"
    return None


def tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens of length >= 3."""
    return {tok for tok in TOKEN_RE.findall(text.lower()) if len(tok) >= 3}


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets; 0.0 when both are empty."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def is_duplicate(
    new_line: str,
    existing_bullet_lines: list[str],
    threshold: float = 0.5,
    min_shared: int = 6,
) -> bool:
    """True iff some existing bullet has jaccard >= threshold AND >= min_shared shared tokens."""
    new_tokens = tokenize(new_line)
    for existing in existing_bullet_lines:
        shared = new_tokens & tokenize(existing)
        if len(shared) >= min_shared and jaccard(new_tokens, tokenize(existing)) >= threshold:
            return True
    return False


def section_bounds(lines: list[str], heading: str) -> tuple[int, int]:
    """Return (start, end) of the section: start is the heading line index
    (len(lines) when the heading is absent), end is the index of the next
    line starting with "## " after start, or len(lines) (EOF)."""
    start = len(lines)
    for i, line in enumerate(lines):
        if line.strip() == heading.strip():
            start = i
            break
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return start, end


def atomic_write(path: str, text: str) -> None:
    """Write text to path via path + ".tmp" then os.replace (atomic).

    The tmp file is created with O_CREAT|O_EXCL|O_NOFOLLOW, so a pre-existing
    file or symlink planted at path + ".tmp" cannot redirect the write
    outside the target directory.
    """
    tmp = path + ".tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def read_lines(path: str) -> list[str]:
    """Read a file as lines; a missing file reads as empty."""
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read().splitlines()


def cmd_append(args: argparse.Namespace) -> int:
    """append subcommand: dedupe stdin bullets and insert them atomically."""
    raw = sys.stdin.read().splitlines()
    bullets = [line.strip() for line in raw]
    bullets = [b for b in bullets if b]
    for b in bullets:
        if not b.startswith("- "):
            sys.stderr.write(f"error: stdin line does not start with '- ' (len={len(b)})\n")
            return 2
    rejected: list[dict[str, object]] = []
    kept: list[str] = []
    for b in bullets:
        reason = scan_rejects(b)
        if reason is not None:
            # never echo bullet content: a rejected bullet may hold a secret
            digest = hashlib.sha256(b.encode("utf-8")).hexdigest()[:12]
            sys.stderr.write(f"rejected ({reason}, len={len(b)}, sha256={digest})\n")
            rejected.append({"reason": reason, "len": len(b), "sha256": digest})
        else:
            kept.append(b)
    bullets = kept
    lines = read_lines(args.file)
    existing_bullets = [line for line in lines if BULLET_RE.match(line)]
    known = list(existing_bullets)
    added: list[str] = []
    duplicates: list[str] = []
    for bullet in bullets:
        if is_duplicate(bullet, known, threshold=args.threshold, min_shared=args.min_shared):
            duplicates.append(bullet)
        else:
            added.append(bullet)
            known.append(bullet)
    if added:
        start, end = section_bounds(lines, args.section)
        if start == len(lines):  # section absent: create at EOF
            new_lines = list(lines)
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.append(args.section)
            new_lines.append("")
            new_lines.append(SECTION_INTRO)
            new_lines.append("")
            new_lines.extend(added)
        else:
            block = list(added)
            if end < len(lines):
                block.append("")  # keep a blank line before the next heading
            elif lines and lines[-1].strip():
                block.insert(0, "")
            new_lines = lines[:end] + block + lines[end:]
        atomic_write(args.file, "\n".join(new_lines) + "\n")
    print(json.dumps({"added": added, "duplicates": duplicates, "rejected": rejected}))
    return 0


def cmd_count(args: argparse.Namespace) -> int:
    """count subcommand: print a bullet count as a bare int.

    With --all: count auto bullets ("- … (src: <8 hex>)") file-wide.
    Otherwise: count "- " bullets inside --section (required in that mode).
    """
    lines = read_lines(args.file)
    if args.all:
        print(sum(1 for line in lines if SRC_BULLET_RE.match(line)))
        return 0
    if not args.section:
        sys.stderr.write("error: count needs --section or --all\n")
        return 2
    start, end = section_bounds(lines, args.section)
    print(sum(1 for line in lines[start + 1 : end] if BULLET_RE.match(line)))
    return 0

def cmd_verify(args: argparse.Namespace) -> int:
    """verify subcommand: gate a unified diff on stdin; exit 0 only if every
    added/removed non-blank line is a complete single-line auto bullet
    (SRC_BULLET_RE) — no new "## " headings, no wrapped bullets, no non-auto
    lines."""
    bad = 0
    for raw in sys.stdin.read().splitlines():
        if raw.startswith(("+++", "---")) or not raw.startswith(("+", "-")):
            continue
        body = raw[1:]
        if not body.strip():
            continue
        if raw.startswith("+") and body.lstrip().startswith("## "):
            sys.stderr.write(f"violation: new heading not allowed: {body[:80]!r}\n")
            bad += 1
        elif not SRC_BULLET_RE.match(body):
            sys.stderr.write(f"violation: not a single-line auto bullet: {body[:80]!r}\n")
            bad += 1
    if bad:
        return 1
    print("ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Atomic, deduplicating learnings append/count for markdown sections."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    ap_app = sub.add_parser("append", help="append deduped bullets from stdin into a section")
    ap_app.add_argument("--file", required=True, help="target markdown file (AGENTS.md)")
    ap_app.add_argument("--section", required=True, help="exact heading line of the section")
    ap_app.add_argument("--threshold", type=float, default=0.5, help="Jaccard duplicate threshold")
    ap_app.add_argument("--min-shared", type=int, default=6, help="minimum shared tokens to count as duplicate")
    ap_cnt = sub.add_parser("count", help="print a bullet count of a section, or of all auto bullets with --all")
    ap_cnt.add_argument("--file", required=True, help="target markdown file (AGENTS.md)")
    ap_cnt.add_argument("--section", required=False, help="exact heading line of the section")
    ap_cnt.add_argument("--all", action="store_true", help="count auto bullets (src-tagged) file-wide instead of a section")
    sub.add_parser("verify", help="gate a unified diff on stdin: only (src: lines may change, no new headings")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "append":
            return cmd_append(args)
        if args.cmd == "verify":
            return cmd_verify(args)
        return cmd_count(args)
    except Exception as e:  # never raise out of main; original file untouched
        sys.stderr.write(f"error: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
