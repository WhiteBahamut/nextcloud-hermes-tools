"""Search tools.

- ``nc_search``: unified OCS search — one GET per provider under
  ``/ocs/v2.php/search/providers/<id>/search``. A provider that is not
  installed on the server (404) becomes a per-provider error entry and never
  fails the whole call. Providers/limit are read from settings on every call.
- ``nc_file_search``: PROPFIND ``Depth: infinity`` + local case-insensitive
  filename filter (server-side DAV SEARCH is NotImplemented); the limit cap is
  applied after the local filter.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import unquote

from . import client, schemas
from .dav import PROPFIND_ALL, entry_from_response, parse_multistatus

log = logging.getLogger(__name__)


def _query_provider(provider: str, term: str, limit: int) -> list:
    """One provider's results; a failure becomes a per-provider error entry."""
    try:
        data = client.ocs(
            "GET",
            f"search/providers/{provider}/search",
            params={"term": term, "limit": limit},
        )
        entries = data if isinstance(data, list) else [data]
        out = []
        for entry in entries:
            if isinstance(entry, dict):
                out.append({"provider": provider, **entry})
            else:
                out.append({"provider": provider, "entry": entry})
        return out
    except Exception as exc:
        log.warning("search provider %s failed: %s", provider, client.redact(str(exc)))
        return [{"provider": provider, "error": client.redact(str(exc))}]


def _search(args):
    term = args.get("term") or ""
    if not term.strip():
        return client.err("empty search term")
    s = client.settings()
    providers = [str(p) for p in (args.get("providers") or s["default_search_providers"])]
    limit = int(args.get("limit") or 0) or s["max_results"]
    results = []
    if providers:
        # Read-only OCS GETs only; httpx.Client is thread-safe. pool.map keeps
        # the providers-argument order (not completion order).
        with ThreadPoolExecutor(max_workers=min(len(providers), 8)) as pool:
            for provider_results in pool.map(lambda p: _query_provider(p, term, limit), providers):
                results.extend(provider_results)
    return client.ok(term=term, count=len(results), results=results)


def _file_search(args):
    term = (args.get("term") or "").lower()
    if not term:
        return client.err("empty search term")
    path = args.get("path") or "/"
    limit = int(args.get("limit") or 100)
    href = client.files_dav(path)
    prefix = client.files_dav("/").rstrip("/")
    resp = client.propfind(href, depth="infinity", body=PROPFIND_ALL)
    target = href.rstrip("/")
    matches = []
    for r in parse_multistatus(resp.text):
        if unquote(r["href"]).rstrip("/") == target:
            continue  # the queried folder itself
        entry = entry_from_response(r, prefix)
        if term in entry["name"].lower():
            matches.append(entry)
            if len(matches) >= limit:
                break
    return client.ok(term=term, path=path, count=len(matches), results=matches)


TOOLS = [
    ("nc_search", schemas.NC_SEARCH, client.tool(_search)),
    ("nc_file_search", schemas.NC_FILE_SEARCH, client.tool(_file_search)),
]
