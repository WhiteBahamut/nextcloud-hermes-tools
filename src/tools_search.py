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

from urllib.parse import unquote

from . import client, schemas
from .dav import PROPFIND_ALL, entry_from_response, parse_multistatus


def _search(args):
    term = args.get("term") or ""
    if not term.strip():
        return client.err("empty search term")
    s = client.settings()
    providers = args.get("providers") or s["default_search_providers"]
    limit = int(args.get("limit") or 0) or s["max_results"]
    results = []
    for provider in providers:
        provider = str(provider)
        try:
            data = client.ocs(
                "GET",
                f"search/providers/{provider}/search",
                params={"term": term, "limit": limit},
            )
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                if isinstance(entry, dict):
                    results.append({"provider": provider, **entry})
                else:
                    results.append({"provider": provider, "entry": entry})
        except Exception as exc:
            results.append({"provider": provider, "error": client.redact(str(exc))})
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
