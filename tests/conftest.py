"""Shared test fixtures.

- Loads ``src/`` as the ``nextcloud_tools`` package (same as the root shim does).
- ``FakeCtx`` captures register_tool/register_hook calls.
- ``nc`` monkeypatches ``client.get_client`` to an httpx.Client with
  MockTransport (no real sockets) and sets only the TALK_* env vars, which
  exercises the fallback path (no `agent` module in the venv ->
  os.environ fallback).
"""

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

_spec = importlib.util.spec_from_file_location(
    "nextcloud_tools", SRC / "__init__.py", submodule_search_locations=[str(SRC)]
)
pkg = importlib.util.module_from_spec(_spec)
sys.modules["nextcloud_tools"] = pkg
_spec.loader.exec_module(pkg)

from nextcloud_tools import client  # noqa: E402


class FakeCtx:
    def __init__(self, settings=None):
        self.tools = {}
        self.hooks = []
        self._settings = dict(settings or {})

    def get_config(self, key, default=None):
        return self._settings.get(key, default)

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs

    def register_hook(self, name, cb):
        self.hooks.append((name, cb))


def make_caller(settings=None):
    """Fresh FakeCtx + registered tools; returns (ctx, call(name, args) -> dict)."""
    ctx = FakeCtx(settings)
    client.configure(ctx)
    pkg.register(ctx)

    def call(name, args=None):
        return json.loads(ctx.tools[name]["handler"](args or {}))

    return ctx, call


@pytest.fixture()
def fake_ctx():
    ctx, _ = make_caller()
    return ctx


@pytest.fixture()
def call(fake_ctx):
    def _call(name, args=None):
        return json.loads(fake_ctx.tools[name]["handler"](args or {}))

    return _call


class MockNc:
    """MockTransport handler: records every request, delegates to self.handler."""

    def __init__(self):
        self.requests = []
        self.handler = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.handler is None:
            return httpx.Response(404, text="not found")
        return self.handler(request)

    def methods(self):
        return [r.method for r in self.requests]

    def find(self, method, path_part):
        return [r for r in self.requests if r.method == method and path_part in r.url.path]


def ocs_ok(data, status=200):
    return httpx.Response(
        status,
        json={"ocs": {"meta": {"status": "ok", "statuscode": 200, "message": "OK"}, "data": data}},
    )


def ocs_err(code, message, http=200):
    return httpx.Response(
        http,
        json={"ocs": {"meta": {"status": "failure", "statuscode": code, "message": message}, "data": []}},
    )


def multistatus(responses):
    """responses: list of (href, props_xml). Returns a 207 multistatus body."""
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns" '
        'xmlns:cal="urn:ietf:params:xml:ns:caldav" xmlns:card="urn:ietf:params:xml:ns:carddav">'
    )
    for href, props in responses:
        body += (
            f"<d:response><d:href>{href}</d:href>"
            "<d:propstat><d:status>HTTP/1.1 200 OK</d:status>"
            f"<d:prop>{props}</d:prop></d:propstat></d:response>"
        )
    body += "</d:multistatus>"
    return httpx.Response(207, text=body, headers={"Content-Type": "application/xml; charset=utf-8"})


@pytest.fixture()
def nc(monkeypatch, fake_ctx):
    monkeypatch.setenv("TALK_SERVER_URL", "https://nc.example")
    monkeypatch.setenv("TALK_USER", "bot")
    monkeypatch.setenv("TALK_APP_PASSWORD", "s3cret-pw")
    mock = MockNc()
    http = httpx.Client(base_url="https://nc.example", transport=httpx.MockTransport(mock),
                        headers={"OCS-APIRequest": "true", "Accept": "application/json"})
    monkeypatch.setattr(client, "get_client", lambda: http)
    return mock
