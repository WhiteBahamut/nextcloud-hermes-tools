"""Logging behavior: src modules log through stdlib ``logging`` under the
``nextcloud_tools.*`` logger namespace, secrets are redacted before they reach a
log record, the plugin attaches no handlers of its own (records propagate to the
host root logger), and the level is driven by the ``log_level`` setting."""

import json
import logging

import httpx
import pytest

import conftest
from conftest import FakeCtx, multistatus
from nextcloud_tools import client, guardrails

PKG_LOGGER = "nextcloud_tools"
FILES = "/remote.php/dav/files/bot"


@pytest.fixture(autouse=True)
def _restore_package_logger_level():
    yield
    logging.getLogger(PKG_LOGGER).setLevel(logging.NOTSET)


def test_tool_wrapper_logs_ok_at_info(nc, call, caplog):
    nc.handler = lambda req: multistatus([
        (f"{FILES}/", '<d:resourcetype><d:collection/></d:resourcetype><oc:fileid>1</oc:fileid>'),
    ])
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        res = call("nc_file_list", {"path": "/"})
    assert res["ok"] is True
    assert any(
        r.levelno == logging.INFO and "nc_file_list" in r.getMessage() and " ok " in r.getMessage()
        for r in caplog.records
    )


def test_tool_wrapper_logs_http_error_at_warning(nc, call, caplog):
    nc.handler = lambda req: httpx.Response(404, text="not found")
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        res = call("nc_file_list", {"path": "/"})
    assert res["ok"] is False
    assert any(
        r.levelno == logging.WARNING and "nc_file_list" in r.getMessage() and "HTTP 404" in r.getMessage()
        for r in caplog.records
    )


def test_tool_wrapper_logs_unexpected_exception_at_error(caplog):
    @client.tool
    def boom(args):
        raise ValueError("kaboom")

    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        out = json.loads(boom({"x": 1}))
    assert out["ok"] is False
    assert any(
        r.levelno == logging.ERROR and "boom" in r.getMessage() and "ValueError" in r.getMessage()
        for r in caplog.records
    )


def test_log_records_never_contain_the_app_password(nc, call, caplog):
    def h(req):
        return httpx.Response(500, text="server exploded, auth used s3cret-pw")

    nc.handler = h
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        call("nc_file_list", {"path": "/"})
    assert "s3cret-pw" not in caplog.text
    for r in caplog.records:
        assert "s3cret-pw" not in r.getMessage()


def test_request_retry_logs_exactly_one_warning(nc, monkeypatch, caplog):
    monkeypatch.setattr(client.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, text="ok")

    nc.handler = h
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        resp = client.request("GET", "/x")
    assert resp.status_code == 200
    assert calls["n"] == 2
    retries = [r for r in caplog.records if r.levelno == logging.WARNING and "retry" in r.getMessage()]
    assert len(retries) == 1
    assert any("--> GET" in r.getMessage() for r in caplog.records)
    assert any("<-- GET 200" in r.getMessage() for r in caplog.records)


def test_set_log_level_from_setting():
    client.configure(FakeCtx({"log_level": "DEBUG"}))
    assert client.set_log_level() == logging.DEBUG
    assert logging.getLogger(PKG_LOGGER).level == logging.DEBUG


def test_set_log_level_unknown_value_falls_back_to_info():
    client.configure(FakeCtx({"log_level": "bogus"}))
    assert client.set_log_level() == logging.INFO
    assert logging.getLogger(PKG_LOGGER).level == logging.INFO


def test_set_log_level_default_is_info():
    client.configure(FakeCtx())
    assert client.set_log_level() == logging.INFO
    assert logging.getLogger(PKG_LOGGER).level == logging.INFO


def test_register_attaches_no_handlers_and_stays_propagating():
    conftest.make_caller()
    logger = logging.getLogger(PKG_LOGGER)
    assert logger.handlers == []
    assert logger.propagate is True


def test_guard_logs_classification_and_hard_block_is_redacted(nc, caplog):
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        res = guardrails.guard("nc_file_delete", {"path": "/x"})
    assert res["action"] == "approve"  # hard_block_destructive defaults to false
    assert any("destructive" in r.getMessage() and "nc_file_delete" in r.getMessage() for r in caplog.records)

    client.configure(FakeCtx({"hard_block_destructive": True}))
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        res = guardrails.guard("nc_file_delete", {"token": "s3cret-pw"})
    assert res["action"] == "block"
    assert any(r.levelno == logging.WARNING and "hard-block" in r.getMessage() for r in caplog.records)
    assert "s3cret-pw" not in caplog.text


def test_register_logs_tool_count_and_applies_info_level(caplog):
    with caplog.at_level(logging.DEBUG, logger=PKG_LOGGER):
        ctx, _ = conftest.make_caller({"log_level": "INFO"})
        assert logging.getLogger(PKG_LOGGER).level == logging.INFO
    assert len(ctx.tools) == 43
    assert any(
        r.levelno == logging.INFO and "registered 43 tools" in r.getMessage() and "0 disabled" in r.getMessage()
        for r in caplog.records
    )


def test_register_applies_configured_warning_level():
    conftest.make_caller({"log_level": "WARNING"})
    assert logging.getLogger(PKG_LOGGER).level == logging.WARNING
