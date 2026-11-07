"""HTTP client layer for the nextcloud-tools Hermes plugin.

- Secrets are read profile-scoped via ``agent.secret_scope.get_secret_str``
  (fail-closed under multiplex); outside the host (tests) we fall back to
  ``os.environ``. Credentials resolve as ``NC_*`` (preferred) with the
  ``TALK_*`` names as fallback — see ``ENV_ALIASES``.
- ``httpx`` is imported lazily inside :func:`get_client` so the package imports
  with the stdlib only.
- Every handler is wrapped in :func:`tool` so it always returns a JSON string
  and never raises.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import logging
import os
import re
import threading
import time
from urllib.parse import quote, unquote

log = logging.getLogger(__name__)

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

REQUIRED_ENV = ("TALK_SERVER_URL", "TALK_USER", "TALK_APP_PASSWORD")

# NC_* is the preferred spelling; the TALK_* names (Talk platform plugin)
# are the fallback. Per-variable precedence: first non-empty wins.
ENV_ALIASES = {
    "TALK_SERVER_URL": "NC_SERVER_URL",
    "TALK_USER": "NC_USER",
    "TALK_APP_PASSWORD": "NC_APP_PASSWORD",
}
KNOWN_ENV = tuple(ENV_ALIASES.values()) + REQUIRED_ENV  # NC_* first, for requires_env metadata

DEFAULT_SEARCH_PROVIDERS = ["files", "fulltextsearch", "talk-message", "calendar", "tasks"]

_CTX = None
_CLIENT = None
_CLIENT_KEY = None
_LOCK = threading.Lock()


class NcError(Exception):
    """HTTP or transport error carrying the status code."""

    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = str(message)


# --- secrets / config --------------------------------------------------------


def _lookup(name: str) -> str:
    try:
        from agent.secret_scope import get_secret_str

        return get_secret_str(name, default="") or ""
    except ImportError:
        # Outside the Hermes host (tests): plain environment fallback.
        return os.environ.get(name, "")


def _secret(name: str) -> str:
    """Resolve a logical credential name; the NC_* alias wins over TALK_*."""
    candidates = (ENV_ALIASES[name], name) if name in ENV_ALIASES else (name,)
    for candidate in candidates:
        value = _lookup(candidate)
        if value:  # empty NC_* falls through to TALK_*
            return value
    return ""


def configure(ctx) -> None:
    """Store the plugin context so runtime settings can be read per call."""
    global _CTX
    _CTX = ctx


def get_config(key, default=None):
    if _CTX is not None:
        try:
            value = _CTX.get_config(key, default)
        except Exception:
            value = None
        if value is not None:
            return value
    return default

def set_log_level(level=None) -> int:
    """Apply the plugin log level to the ``nextcloud_tools`` package logger.

    Resolves ``level`` or the ``log_level`` setting (default INFO), maps it via
    LOG_LEVELS (unknown -> INFO) and returns the int. Attaches NO handlers:
    records propagate to the Hermes host root logger (agent.log/errors.log).
    """
    resolved = LOG_LEVELS.get(str(level or get_config("log_level", "INFO") or "INFO").upper(), logging.INFO)
    logging.getLogger("nextcloud_tools").setLevel(resolved)
    return resolved


def settings() -> dict:
    """Snapshot of the plugin settings (read fresh on every call)."""
    providers = get_config("default_search_providers", DEFAULT_SEARCH_PROVIDERS)
    skip = get_config("talk_skip_tokens", []) or []
    disabled = get_config("disabled_tools", []) or []
    return {
        "ca_bundle": get_config("ca_bundle", "") or "",
        "default_search_providers": [str(p) for p in (providers or DEFAULT_SEARCH_PROVIDERS)],
        "max_results": int(get_config("max_results", 20) or 20),
        "request_timeout": float(get_config("request_timeout", 30.0) or 30.0),
        "talk_include_dms": bool(get_config("talk_include_dms", False)),
        "talk_skip_tokens": [str(t) for t in skip],
        "disabled_tools": [str(t) for t in disabled],
        "hard_block_destructive": bool(get_config("hard_block_destructive", False)),
        "log_level": str(get_config("log_level", "INFO") or "INFO").upper(),
    }


def configured() -> bool:
    """check_fn for every tool: all three credentials present (fail closed)."""
    try:
        return all(bool(_secret(name)) for name in REQUIRED_ENV)
    except Exception:
        return False


# --- paths / URLs ------------------------------------------------------------


def enc_path(path: str) -> str:
    """URL-encode every segment (safe="") and rejoin with '/'; keeps leading '/'.

    Dot segments ('.'/'..', including percent-encoded forms) are rejected:
    httpx and the web server normalize them, which would let a caller escape
    the DAV root (e.g. files_dav("../../..") -> "/") with bot credentials.
    """
    out = []
    for seg in str(path).split("/"):
        if unquote(seg) in (".", ".."):
            raise NcError(400, f"path traversal rejected: {unquote(seg)!r} segment")
        out.append(quote(seg, safe=""))
    return "/".join(out)


def abs_url(path: str) -> str:
    server = _secret("TALK_SERVER_URL").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return server + path


def files_dav(path: str = "") -> str:
    """WebDAV href of a path inside the bot's files root."""
    user = quote(_secret("TALK_USER"), safe="")
    p = enc_path(path).strip("/")
    base = f"/remote.php/dav/files/{user}"
    return f"{base}/{p}" if p else f"{base}/"


def cal_dav(calendar: str) -> str:
    user = quote(_secret("TALK_USER"), safe="")
    return f"/remote.php/dav/calendars/{user}/{enc_path(calendar).strip('/')}/"


def book_dav(book: str) -> str:
    user = quote(_secret("TALK_USER"), safe="")
    return f"/remote.php/dav/addressbooks/{user}/{enc_path(book).strip('/')}/"


# --- redaction / results -----------------------------------------------------


def redact(text) -> str:
    """Strip app passwords (both NC_*/TALK_* spellings, plus URL-encoded form),
    base64(user:password), URL userinfo (user:pass@host) and Authorization values.
    Never raises — a failure here must not break error reporting."""
    if not isinstance(text, str):
        text = str(text)
    try:
        users = {v for v in (_lookup("NC_USER"), _lookup("TALK_USER")) if v}
        passwords = {v for v in (_lookup("NC_APP_PASSWORD"), _lookup("TALK_APP_PASSWORD")) if v}
    except Exception:
        users, passwords = set(), set()
    for secret in passwords | users:
        text = text.replace(secret, "***")
    for u in users:
        for p in passwords:
            text = text.replace(base64.b64encode(f"{u}:{p}".encode()).decode(), "***")
    for p in passwords:
        text = text.replace(quote(p, safe=""), "***")
    text = re.sub(r"(://[^/@\s:]+):[^/@\s]+@", r"\1:***@", text)  # user:pass@host userinfo
    text = re.sub(r"(?i)(authorization:\s*(?:(?:basic|bearer)\s+)?)\S+", r"\1***", text)
    text = re.sub(r"(?i)(bearer\s+)\S+", r"\1***", text)
    return text

def _log_safe(text) -> str:
    """redact() for log lines; any failure -> fixed placeholder (logging must never break a handler)."""
    try:
        return redact(text)
    except Exception:
        return "<unloggable>"


def err(message, **kw) -> str:
    try:
        msg = redact(message)
    except Exception:
        msg = "internal error (message suppressed)"  # never leak the raw text
    return json.dumps({"ok": False, "error": msg, **kw}, ensure_ascii=False)


def ok(**kw) -> str:
    return json.dumps({"ok": True, **kw}, ensure_ascii=False)


def tool(fn):
    """Wrap a handler: never raises, always returns a JSON string.

    Logs every call through the module logger (entry at DEBUG, outcome at
    INFO/WARNING/ERROR); all dynamic text is redacted before logging. The
    logged name is the wrapper's ``__name__``; register() sets it to the
    registered tool name (e.g. ``nc_file_list``).
    """

    @functools.wraps(fn)
    def wrapper(args=None, **_kwargs):
        start = time.monotonic()
        if log.isEnabledFor(logging.DEBUG):
            try:
                log.debug("%s args=%s", wrapper.__name__, redact(json.dumps(args or {}))[:300])
            except Exception:
                log.debug("%s args=<unloggable>", wrapper.__name__)
        try:
            result = fn(args or {})
        except NcError as exc:
            log.warning("%s failed HTTP %s (%.3fs): %s", wrapper.__name__, exc.status, time.monotonic() - start, _log_safe(exc.message))
            return err(f"HTTP {exc.status}: {exc.message}", status=exc.status)
        except Exception as exc:  # handlers must never raise
            log.error("%s raised %s (%.3fs): %s", wrapper.__name__, type(exc).__name__, time.monotonic() - start, _log_safe(str(exc)))
            return err(f"{type(exc).__name__}: {exc}")
        log.info("%s ok (%.3fs)", wrapper.__name__, time.monotonic() - start)
        return result

    return wrapper


# --- transport ---------------------------------------------------------------


def get_client():
    """Build/cache the httpx.Client (key = server+user+password+ca_bundle+timeout).

    Password and timeout are part of the key so rotating the app password in
    .env or changing the request_timeout setting rebuilds the client instead
    of serving stale auth/timeout until process restart. The key holds the
    password in memory (the client auth already does) — never log it.
    """
    global _CLIENT, _CLIENT_KEY
    server = _secret("TALK_SERVER_URL").rstrip("/")
    user = _secret("TALK_USER")
    password = _secret("TALK_APP_PASSWORD")
    if not (server and user and password):
        raise NcError(0, "missing credentials: set NC_SERVER_URL, NC_USER, NC_APP_PASSWORD (or TALK_SERVER_URL, TALK_USER, TALK_APP_PASSWORD)")
    ca_bundle = get_config("ca_bundle", "") or ""
    timeout = float(get_config("request_timeout", 30.0) or 30.0)
    key = (server, user, password, ca_bundle, timeout)
    with _LOCK:
        if _CLIENT is not None and _CLIENT_KEY == key:
            return _CLIENT
        import httpx

        old = _CLIENT
        client = httpx.Client(
            base_url=server,
            auth=(user, password),
            verify=ca_bundle if ca_bundle else True,
            timeout=timeout,
            headers={"OCS-APIRequest": "true", "Accept": "application/json"},
        )
        _CLIENT = client
        _CLIENT_KEY = key
        log.debug("httpx client rebuilt server=%s user=%s ca_bundle=%s timeout=%s", server, user, ca_bundle or "", timeout)
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        return client


def _retryable(exc) -> bool:
    import httpx

    return isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError))


RETRY_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PROPFIND", "REPORT"})


def request(method, path, *, params=None, data=None, json_body=None, content=None, headers=None):
    """One HTTP request; retries once (0.5 s backoff) on connect/read/protocol errors.

    Only safe methods (GET/HEAD/OPTIONS/PROPFIND/REPORT) are retried — a dropped
    connection after server-side processing must not re-send a write (PUT/POST/
    DELETE/MOVE/...) blindly.
    """
    client = get_client()
    safe = method.upper() in RETRY_SAFE_METHODS
    debug = log.isEnabledFor(logging.DEBUG)
    for attempt in (0, 1):
        if debug:
            log.debug("--> %s %s", method, _log_safe(path))
        start = time.monotonic()
        try:
            resp = client.request(
                method, path, params=params, data=data, json=json_body, content=content, headers=headers
            )
        except Exception as exc:
            if attempt == 1 or not safe or not _retryable(exc):
                raise
            log.warning("retry %s %s after %s (attempt 1)", method, _log_safe(path), type(exc).__name__)
            time.sleep(0.5)
            continue
        if debug:
            log.debug("<-- %s %d in %.3fs", method, resp.status_code, time.monotonic() - start)
        return resp


def resp_message(resp) -> str:
    try:
        payload = resp.json()
        message = payload.get("ocs", {}).get("meta", {}).get("message")
        if message:
            return str(message)
    except Exception:
        pass
    return (resp.text or "")[:300]


def require(resp, allowed=(200,)):
    if resp.status_code not in allowed:
        raise NcError(resp.status_code, resp_message(resp))
    return resp


# --- DAV helpers -------------------------------------------------------------


def propfind(path, depth=1, body=None):
    """PROPFIND; the server answers 200 AND 207 — both accepted. Depth is always sent."""
    headers = {"Depth": str(depth), "Content-Type": "application/xml; charset=utf-8"}
    payload = body.encode("utf-8") if isinstance(body, str) else body
    return require(request("PROPFIND", path, content=payload, headers=headers), (200, 207))


def dav_get(path, headers=None):
    return require(request("GET", path, headers=headers), (200,))


def dav_put(path, content, content_type=""):
    headers = {"Content-Type": content_type} if content_type else None
    return require(request("PUT", path, content=content, headers=headers), (200, 201, 204))


def dav_mkcol(path):
    return require(request("MKCOL", path), (201,))


def dav_move(source, destination, overwrite=True):
    headers = {"Destination": destination, "Overwrite": "T" if overwrite else "F"}
    return request("MOVE", source, headers=headers)


def dav_delete(path, headers=None):
    return request("DELETE", path, headers=headers)


def dav_proppatch(path, body):
    headers = {"Content-Type": "application/xml; charset=utf-8"}
    return require(request("PROPPATCH", path, content=body.encode("utf-8"), headers=headers), (200, 207))


# --- OCS helper ----------------------------------------------------------------


def ocs(method, path, *, params=None, data=None):
    """Call an OCS v2 endpoint; unwraps the {"ocs": {"meta", "data"}} envelope."""
    resp = request(method, "/ocs/v2.php/" + str(path).lstrip("/"), params=params, data=data)
    try:
        payload = resp.json()
    except Exception:
        raise NcError(resp.status_code, (resp.text or "")[:300])
    ocs_part = payload.get("ocs", {})
    meta = ocs_part.get("meta", {})
    try:
        code = int(meta.get("statuscode", resp.status_code))
    except (TypeError, ValueError):
        code = resp.status_code
    if resp.status_code != 200 or code != 200:
        raise NcError(code, meta.get("message") or (resp.text or "")[:300])
    return ocs_part.get("data")


# --- read-back verification ----------------------------------------------------


def verify_file_content(path, content: bytes) -> bool:
    resp = dav_get(path)
    return hashlib.sha256(resp.content).hexdigest() == hashlib.sha256(content).hexdigest()


def verify_exists(path) -> bool:
    try:
        propfind(path, depth=0)
        return True
    except NcError:
        return False


def verify_gone(path) -> bool:
    try:
        propfind(path, depth=0)
        return False
    except NcError as exc:
        return exc.status == 404


def put_verified(path, content: bytes, content_type: str = "") -> None:
    """PUT + server-attested verification.

    Sends ``OC-Checksum: SHA256:<hex>`` with the PUT; when the response echoes
    an ``OC-Checksum`` header, the sha256 is compared from the header (no
    re-download of the body). When the server does not echo it, falls back to
    the full GET read-back (:func:`verify_file_content`). Raises NcError on
    any failure; never returns without verification.
    """
    digest = hashlib.sha256(content).hexdigest()
    headers = {"OC-Checksum": f"SHA256:{digest}"}
    if content_type:
        headers["Content-Type"] = content_type
    resp = require(request("PUT", path, content=content, headers=headers), (200, 201, 204))
    echoed = (resp.headers.get("OC-Checksum") or "").strip()
    m = re.match(r"(?i)sha256:([0-9a-f]+)", echoed)
    if m:
        if m.group(1).lower() != digest.lower():
            log.warning("write verification failed for %s (OC-Checksum mismatch)", _log_safe(path))
            raise NcError(500, "write verification failed (OC-Checksum mismatch)")
        return
    if not verify_file_content(path, content):
        log.warning("write verification failed for %s (sha256 mismatch)", _log_safe(path))
        raise NcError(500, "write verification failed (sha256 mismatch)")
