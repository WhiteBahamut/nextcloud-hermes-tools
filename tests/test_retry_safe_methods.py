"""Only safe HTTP methods are retried; writes are never re-sent blindly (review P5)."""

import httpx
import pytest

from nextcloud_tools import client


def test_no_retry_on_unsafe_methods_but_safe_still_retries(nc, monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        raise httpx.ConnectError("refused")

    nc.handler = h
    with pytest.raises(httpx.ConnectError):
        client.request("POST", "/x", data={"a": "b"})
    assert calls["n"] == 1  # write not re-sent blindly
    with pytest.raises(httpx.ConnectError):
        client.request("PROPFIND", "/x")
    assert calls["n"] == 3  # safe method retried once (2 attempts)
