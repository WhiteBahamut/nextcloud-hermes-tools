"""Install-time version check: Hermes agent + Nextcloud server vs tested ranges.

Runs once from ``register()`` (``src/__init__.py``) — the load/install entry
point of a directory plugin. The Nextcloud server version comes from a single
unauthenticated ``GET /status.php`` (flat JSON with the ``version`` field,
e.g. ``"35.0.2.2"``; see the nc-compat-nextcloud skill step 2) with a short
timeout and NO retry, so a dead server cannot hang agent startup. The Hermes
agent version comes from the installed ``hermes-agent`` distribution metadata
(``importlib.metadata`` — stdlib, no Hermes internal import).

Log level policy: INFO when the detected version is inside the tested range,
WARNING otherwise (older, newer, or undeterminable) — a warning is the loud
signal that a compat check has not run against this version. Never raises.
"""

from __future__ import annotations

import importlib.metadata
import logging
import re

from . import client

log = logging.getLogger(__name__)

# bump after every nc-compat-hermes / nc-compat-nextcloud run
HERMES_TESTED = (0, 23)  # last Hermes line checked green (v0.23.0); (major, minor), patch ignored
# bump after every nc-compat-hermes / nc-compat-nextcloud run
NC_TESTED_MAJOR_MIN = 33  # support floor: oldest supported major per the NC maintenance schedule
NC_TESTED_MAJOR_MAX = 35  # newest major the plugin was checked against (35.0.2.2)
STATUS_TIMEOUT = 5.0  # seconds for the install-time /status.php probe


def parse_version(text) -> tuple[int, ...] | None:
    """Leading integer components of a version string; ``None`` on garbage.

    Strips a leading ``v``, splits on ``.``/``-`` and keeps the leading digits
    of each component, stopping at the first component without any:
    ``"v0.23.0" -> (0, 23, 0)``, ``"35.0.2.2" -> (35, 0, 2, 2)``,
    ``"0.23" -> (0, 23)``, ``"garbage"``/``""`` -> ``None``.
    """
    if not isinstance(text, str):
        return None
    parts: list[int] = []
    for chunk in re.split(r"[.\-]", text.strip().lstrip("vV")):
        m = re.match(r"\d+", chunk)
        if not m:
            break
        parts.append(int(m.group()))
    return tuple(parts) if parts else None


def hermes_version() -> str:
    """Version of the installed ``hermes-agent`` distribution; ``""`` if unknown."""
    try:
        return importlib.metadata.version("hermes-agent")
    except Exception:
        return ""


def _server_version(err_out: list[str] | None = None) -> str:
    """Nextcloud server version from ``GET /status.php``; ``""`` on any failure.

    Deliberately bypasses ``client.request()``: no retry, short timeout — the
    probe runs at plugin load and must never hang startup. ``/status.php`` is a
    fixed literal, no path encoding needed. On failure the reason is appended
    to ``err_out`` (if given) so the caller can log it redacted.
    """
    try:
        http = client.get_client()
        resp = http.get("/status.php", timeout=STATUS_TIMEOUT)
        if resp.status_code != 200:
            if err_out is not None:
                err_out.append(f"HTTP {resp.status_code}")
            return ""
        data = resp.json()
        if not isinstance(data, dict):
            if err_out is not None:
                err_out.append("non-dict JSON body")
            return ""
        version = data.get("version")
        if not isinstance(version, str) or not version:
            if err_out is not None:
                err_out.append("missing 'version' field")
            return ""
        return version
    except Exception as exc:
        if err_out is not None:
            err_out.append(str(exc))
        return ""


def check_versions() -> None:
    """Log Hermes + Nextcloud versions at INFO (tested) / WARNING (not tested).

    Never raises — a failure here must not break plugin load; the residual
    risk is logged at DEBUG with the traceback.
    """
    try:
        hv = hermes_version()
        pv = parse_version(hv)
        if pv is not None and pv[:2] == HERMES_TESTED:
            log.info(
                "Hermes agent v%s is within the tested line v%d.%d.x (nc-compat-hermes)",
                hv, HERMES_TESTED[0], HERMES_TESTED[1],
            )
        elif pv is not None and pv[:2] < HERMES_TESTED:
            log.warning(
                "Hermes agent v%s is OLDER than the last tested v%d.%d.0 - verify the plugin contract before use",
                hv, HERMES_TESTED[0], HERMES_TESTED[1],
            )
        elif pv is not None:
            log.warning(
                "Hermes agent v%s is NEWER than the last tested v%d.%d.0 - run the nc-compat-hermes check",
                hv, HERMES_TESTED[0], HERMES_TESTED[1],
            )
        else:
            log.warning("could not determine the Hermes agent version (hermes-agent distribution not installed?)")

        if not client.configured():
            log.info("Nextcloud credentials not configured (NC_*/TALK_* unset); skipping the server version check")
            return
        err_out: list[str] = []
        sv = _server_version(err_out)
        pv = parse_version(sv)
        major = pv[0] if pv else None
        if major is not None and NC_TESTED_MAJOR_MIN <= major <= NC_TESTED_MAJOR_MAX:
            log.info(
                "Nextcloud server v%s is within the tested range NC %d-%d (nc-compat-nextcloud)",
                sv, NC_TESTED_MAJOR_MIN, NC_TESTED_MAJOR_MAX,
            )
        elif major is not None and major < NC_TESTED_MAJOR_MIN:
            log.warning(
                "Nextcloud server v%s is below the support floor NC %d - upgrade the server",
                sv, NC_TESTED_MAJOR_MIN,
            )
        elif major is not None:
            log.warning(
                "Nextcloud server v%s is NEWER than the last tested NC %d - run the nc-compat-nextcloud check",
                sv, NC_TESTED_MAJOR_MAX,
            )
        else:
            log.warning(
                "could not determine the Nextcloud server version from /status.php (%s)",
                client._log_safe(err_out[0] if err_out else "unknown error"),
            )
    except Exception:
        log.debug("version check failed", exc_info=True)
