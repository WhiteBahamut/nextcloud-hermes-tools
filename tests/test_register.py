import re
from pathlib import Path

import nextcloud_tools as pkg
from nextcloud_tools import client


def test_registers_43_tools_under_nextcloud_toolset(fake_ctx):
    assert len(fake_ctx.tools) == 43
    assert {t["toolset"] for t in fake_ctx.tools.values()} == {"nextcloud"}
    for name, t in fake_ctx.tools.items():
        assert isinstance(t["schema"]["parameters"], dict), name
        assert t["schema"]["description"], name
        assert callable(t["handler"]), name
        assert t["check_fn"] is client.configured, name
        assert t["requires_env"] == list(client.KNOWN_ENV), name


def test_exactly_one_pre_tool_call_hook(fake_ctx):
    assert [h[0] for h in fake_ctx.hooks] == ["pre_tool_call"]


def test_manifest_provides_tools_matches_registered(fake_ctx):
    manifest = (Path(__file__).resolve().parent.parent / "plugin.yaml").read_text()
    provided = set(re.findall(r"^  - (nc_\w+)$", manifest, re.M))
    assert len(provided) == 43
    assert provided == set(fake_ctx.tools)
    assert "kind:" not in manifest  # only 5 valid kinds exist; omission = standalone
    for var in client.KNOWN_ENV:
        assert f"- {var}" in manifest


def test_configured_gating(monkeypatch):
    for var in client.KNOWN_ENV:
        monkeypatch.delenv(var, raising=False)
    assert client.configured() is False
    monkeypatch.setenv("TALK_SERVER_URL", "https://nc.example")
    assert client.configured() is False
    monkeypatch.setenv("TALK_USER", "bot")
    assert client.configured() is False
    monkeypatch.setenv("TALK_APP_PASSWORD", "pw")
    assert client.configured() is True
    # NC_* spelling only (TALK_* absent) also satisfies gating
    for var in ("TALK_SERVER_URL", "TALK_USER", "TALK_APP_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NC_SERVER_URL", "https://nc.example")
    monkeypatch.setenv("NC_USER", "bot")
    monkeypatch.setenv("NC_APP_PASSWORD", "pw")
    assert client.configured() is True
    # both spellings set: still True
    monkeypatch.setenv("TALK_SERVER_URL", "https://talk.example")
    monkeypatch.setenv("TALK_USER", "talkbot")
    monkeypatch.setenv("TALK_APP_PASSWORD", "talkpw")
    assert client.configured() is True


def test_register_is_idempotent_name_set():
    import conftest

    _ctx, _call = conftest.make_caller()
    assert len(_ctx.tools) == 43
    assert pkg.TOOLSET == "nextcloud"
