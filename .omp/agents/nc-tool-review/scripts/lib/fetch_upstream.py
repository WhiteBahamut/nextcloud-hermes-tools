#!/usr/bin/env python3
"""Fetch the pinned upstream sources (``upstream_pins.json``) into ``.cache/upstream/``.

Determinism mechanism for layers 1-3: every pin is content-addressed by sha256 in
``upstream_lock.json``. With an intact cache + lock this script performs NO network
access and rewrites nothing, so repeated runs are byte-identical. Network is needed
only when a pin is missing from the cache or the lock does not match yet.

Usage (paths are resolved relative to this file, so cwd does not matter):

    python3 lib/fetch_upstream.py                # verify/fill cache against the lock
    python3 lib/fetch_upstream.py --update-lock  # re-download every pin, rewrite the lock
    python3 lib/fetch_upstream.py --offline      # no network; fail if cache+lock incomplete

Exit 0 iff every pin is cached and lock-consistent. A fetch URL that 404s fails with
the URL — fix by updating the pin in upstream_pins.json, never by guessing a new path
inside a check script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent  # scripts/lib
SCRIPTS = HERE.parent
CACHE = SCRIPTS / ".cache" / "upstream"
PINS_FILE = HERE / "upstream_pins.json"
LOCK_FILE = HERE / "upstream_lock.json"
UA = {"User-Agent": "nc-tool-review-scripts/1.0 (pinned offline validation)"}
TIMEOUT = 60


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def write_lock(lock: dict) -> None:
    body = {
        "comment": json.loads(PINS_FILE.read_text(encoding="utf-8")).get("comment", ""),
        "pins": {name: lock["pins"][name] for name in sorted(lock["pins"])},
    }
    LOCK_FILE.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--update-lock", action="store_true", help="re-download all pins, rewrite the lock")
    ap.add_argument("--offline", action="store_true", help="no network; require cache+lock to match")
    args = ap.parse_args()

    pins: dict[str, dict] = json.loads(PINS_FILE.read_text(encoding="utf-8"))["pins"]
    lock = load_json(LOCK_FILE)
    lock.setdefault("pins", {})
    lock["pins"] = {k: v for k, v in lock["pins"].items() if k in pins}  # prune removed pins
    CACHE.mkdir(parents=True, exist_ok=True)
    for stale in CACHE.iterdir():  # prune cache files of removed pins
        if stale.is_file() and stale.name not in pins:
            stale.unlink()

    failures: list[str] = []
    lock_changed = False
    for name in sorted(pins):
        pin = pins[name]
        url = pin["url"]
        cache_file = CACHE / name
        entry = lock["pins"].get(name)

        if args.update_lock:
            try:
                data = fetch(url)
            except Exception as exc:  # noqa: BLE001 - report the URL, fail loudly
                failures.append(f"{name}: fetch failed for {url}: {exc}")
                continue
            cache_file.write_bytes(data)
            lock["pins"][name] = {"url": url, "sha256": sha256_hex(data), "bytes": len(data)}
            lock_changed = True
            print(f"PIN {name} fetched sha256={sha256_hex(data)[:12]} bytes={len(data)}")
            continue

        if cache_file.exists():
            data = cache_file.read_bytes()
            digest = sha256_hex(data)
            if entry and entry.get("url") == url and entry.get("sha256") == digest:
                print(f"PIN {name} cached sha256={digest[:12]} bytes={len(data)}")
                continue
            if not entry:
                # Cache present but never locked (e.g. cache copied in): adopt it.
                lock["pins"][name] = {"url": url, "sha256": digest, "bytes": len(data)}
                lock_changed = True
                print(f"PIN {name} adopted sha256={digest[:12]} bytes={len(data)}")
                continue
            if args.offline:
                failures.append(f"{name}: cache does not match lock and --offline forbids fetching ({url})")
                continue
            # Lock mismatch: re-fetch to see whether upstream drifted or the cache is stale.
            try:
                data = fetch(url)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{name}: fetch failed for {url}: {exc}")
                continue
            new_digest = sha256_hex(data)
            if new_digest != entry.get("sha256"):
                failures.append(
                    f"{name}: upstream content drifted from the lock ({url}: "
                    f"lock {entry.get('sha256', '?')[:12]} vs fetched {new_digest[:12]}); "
                    "run with --update-lock to re-pin"
                )
                continue
            cache_file.write_bytes(data)
            print(f"PIN {name} refetched-matches-lock sha256={new_digest[:12]} bytes={len(data)}")
            continue

        # No cache entry.
        if args.offline:
            failures.append(f"{name}: not in cache and --offline forbids fetching ({url})")
            continue
        try:
            data = fetch(url)
        except urllib.error.HTTPError as exc:
            failures.append(f"{name}: HTTP {exc.code} for {url} — update the pin in upstream_pins.json")
            continue
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: fetch failed for {url}: {exc}")
            continue
        digest = sha256_hex(data)
        cache_file.write_bytes(data)
        if entry and entry.get("url") == url and entry.get("sha256") != digest:
            failures.append(
                f"{name}: fetched content differs from lock ({url}: lock {entry.get('sha256', '?')[:12]} "
                f"vs fetched {digest[:12]}); run with --update-lock to re-pin"
            )
            continue
        lock["pins"][name] = {"url": url, "sha256": digest, "bytes": len(data)}
        lock_changed = True
        print(f"PIN {name} fetched sha256={digest[:12]} bytes={len(data)}")

    if lock_changed:
        write_lock(lock)
        print(f"LOCK updated ({len(lock['pins'])} pins)")

    if failures:
        for line in failures:
            print(f"FAIL {line}")
        print(f"FETCH-FAIL ({len(failures)} pin(s) unresolved)")
        return 1
    print(f"FETCH-OK ({len(pins)} pins cached and lock-consistent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
