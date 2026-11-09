"""Install-time version check (``src/compat.py``): Hermes agent + Nextcloud
server versions are logged at INFO when inside the tested ranges and WARNING
otherwise (older / newer / undeterminable). Hermetic: ``httpx.MockTransport``
only, no real sockets."""

import importlib.metadata
import logging
from importlib.metadata import PackageNotFoundError

import httpx
import pytest

import conftest
from nextcloud_tools import client, compat

PKG_LOGGER = "nextcloud_tools"


@pytest.fixture(autouse=True)
def _restore_package_logger_level():
    yield
    logging.getLogger(PKG_LOGGER).setLevel(logging.NOTSET)


def _patch_hermes(monkeypatch, version):
    monkeypatch.setattr(importlib.metadata, "version", lambda name: version)


def _patch_hermes_raises(monkeypatch, exc):
    def _raise(name):
        raise exc

    monkeypatch.setattr(importlib.metadata, "version", _raise)


def _mock_client(monkeypatch, handler):
    """Same wiring as the ``nc`` fixture: creds in env, get_client -> MockTransport."""
    monkeypatch.setenv("TALK_SERVER_URL", "https://nc.example")
    monkeypatch.setenv("TALK_USER", "bot")
    monkeypatch.setenv("TALK_APP_PASSWORD", "s3cret-pw")
    mock = conftest.MockNc()
    mock.handler = handler
    http = httpx.Client(base_url="https://nc.example", transport=httpx.MockTransport(mock),
                        headers={"OCS-APIRequest": "true", "Accept": "application/json"})
    monkeypatch.setattr(client, "get_client", lambda: http)
    return mock


def _status(version):
    return lambda req: httpx.Response(200, json={"version": version, "installed": True, "edition": ""})


@pytest.mark.parametrize("text,expected", [
    ("v0.23.0", (0, 23, 0)),
    ("35.0.2.2", (35, 0, 2, 2)),
    ("0.23", (0, 23)),
    ("v2026.9.24", (2026, 9, 24)),
    ("garbage", None),
    ("", None),
    (None, None),
])
def test_parse_version(text, expected):
    assert compat.parse_version(text) == expected


def test_hermes_version_reads_distribution_metadata(monkeypatch):
    _patch_hermes(monkeypatch, "0.23.0")
    assert compat.hermes_version() == "0.23.0"


def test_hermes_version_missing_distribution_returns_empty(monkeypatch):
    _patch_hermes_raises(monkeypatch, PackageNotFoundError("hermes-agent"))
    assert compat.hermes_version() == ""


def test_check_versions_tested_versions_log_info_and_probe_once(monkeypatch, caplog):
    _patch_hermes(monkeypatch, "0.23.4")
    mock = _mock_client(monkeypatch, _status("35.0.2.2"))
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        compat.check_versions()
    assert any(
        r.levelno == logging.INFO and "within the tested line" in r.getMessage() and "0.23.4" in r.getMessage()
        for r in caplog.records
    )
    assert any(
        r.levelno == logging.INFO and "within the tested range" in r.getMessage() and "35.0.2.2" in r.getMessage()
        for r in caplog.records
    )
    assert len(mock.find("GET", "/status.php")) == 1
    assert "s3cret-pw" not in caplog.text


@pytest.mark.parametrize("server_version,fragment", [
    ("32.0.0", "below the support floor"),
    ("36.0.1", "NEWER than the last tested NC 35"),
])
def test_check_versions_server_outside_tested_range_warns(monkeypatch, caplog, server_version, fragment):
    _patch_hermes(monkeypatch, "0.23.0")
    _mock_client(monkeypatch, _status(server_version))
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        compat.check_versions()
    assert any(
        r.levelno == logging.WARNING and fragment in r.getMessage() and server_version in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.parametrize("hermes,fragment", [
    ("0.22.9", "OLDER than the last tested"),
    ("0.24.0", "NEWER than the last tested"),
])
def test_check_versions_hermes_outside_tested_line_warns(monkeypatch, caplog, hermes, fragment):
    _patch_hermes(monkeypatch, hermes)
    _mock_client(monkeypatch, _status("35.0.2.2"))
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        compat.check_versions()
    assert any(
        r.levelno == logging.WARNING and fragment in r.getMessage() and hermes in r.getMessage()
        for r in caplog.records
    )


def test_check_versions_hermes_unknown_warns(monkeypatch, caplog):
    _patch_hermes_raises(monkeypatch, PackageNotFoundError("hermes-agent"))
    _mock_client(monkeypatch, _status("35.0.2.2"))
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        compat.check_versions()
    assert any(
        r.levelno == logging.WARNING and "could not determine the Hermes agent version" in r.getMessage()
        for r in caplog.records
    )


def test_check_versions_status_http_error_warns(monkeypatch, caplog):
    _patch_hermes(monkeypatch, "0.23.0")
    _mock_client(monkeypatch, lambda req: httpx.Response(404, text="not found"))
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        compat.check_versions()
    assert any(
        r.levelno == logging.WARNING and "could not determine the Nextcloud server version" in r.getMessage()
        for r in caplog.records
    )


def test_check_versions_transport_error_warns_and_never_raises(monkeypatch, caplog):
    _patch_hermes(monkeypatch, "0.23.0")

    def _boom(req):
        raise httpx.ConnectError("no route")

    _mock_client(monkeypatch, _boom)
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        assert compat.check_versions() is None
    assert any(
        r.levelno == logging.WARNING and "could not determine the Nextcloud server version" in r.getMessage()
        for r in caplog.records
    )


def test_check_versions_unconfigured_skips_server_probe(monkeypatch, caplog):
    for var in client.KNOWN_ENV:
        monkeypatch.delenv(var, raising=False)
    mock = conftest.MockNc()
    http = httpx.Client(base_url="https://nc.example", transport=httpx.MockTransport(mock))
    monkeypatch.setattr(client, "get_client", lambda: http)
    _patch_hermes(monkeypatch, "0.23.0")
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        compat.check_versions()
    assert any(
        r.levelno == logging.INFO and "skipping the server version check" in r.getMessage()
        for r in caplog.records
    )
    assert mock.requests == []


def test_check_versions_never_raises(monkeypatch, caplog):
    monkeypatch.setenv("TALK_SERVER_URL", "https://nc.example")
    monkeypatch.setenv("TALK_USER", "bot")
    monkeypatch.setenv("TALK_APP_PASSWORD", "s3cret-pw")
    monkeypatch.setattr(client, "get_client", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    _patch_hermes(monkeypatch, "0.23.0")
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        assert compat.check_versions() is None
    assert any(
        r.levelno == logging.WARNING and "could not determine the Nextcloud server version" in r.getMessage()
        for r in caplog.records
    )
    assert "boom" in caplog.text  # the (redacted) cause is logged
    assert "s3cret-pw" not in caplog.text


def test_register_probes_status_php_once_when_configured(monkeypatch):
    _patch_hermes(monkeypatch, "0.23.0")
    mock = _mock_client(monkeypatch, _status("35.0.2.2"))
    ctx, _ = conftest.make_caller()
    assert len(ctx.tools) == 44
    assert len(mock.find("GET", "/status.php")) == 1


def test_register_without_credentials_makes_no_requests(monkeypatch):
    for var in client.KNOWN_ENV:
        monkeypatch.delenv(var, raising=False)
    mock = conftest.MockNc()
    http = httpx.Client(base_url="https://nc.example", transport=httpx.MockTransport(mock))
    monkeypatch.setattr(client, "get_client", lambda: http)
    _patch_hermes(monkeypatch, "0.23.0")
    ctx, _ = conftest.make_caller()
    assert len(ctx.tools) == 44
    assert mock.requests == []
