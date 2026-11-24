"""post_tool_call usage-stats observer: counts, ok/error split, never raises."""

import logging

from nextcloud_tools import stats


def setup_function(_):
    stats.reset()


def test_observe_counts_nc_tools_only():
    stats.observe(tool_name="nc_file_list", result='{"ok": true}', duration_ms=12)
    stats.observe(tool_name="nc_file_list", result='{"ok": false, "error": "x"}', duration_ms=8)
    stats.observe(tool_name="terminal", result='{"output": "hi"}', duration_ms=5)
    stats.observe(tool_name="", result=None)
    snap = stats.snapshot()
    assert snap["total_calls"] == 2
    assert len(snap["tools"]) == 1
    entry = snap["tools"][0]
    assert entry["tool"] == "nc_file_list"
    assert entry["calls"] == 2 and entry["ok"] == 1 and entry["error"] == 1
    assert entry["total_ms"] == 20.0 and entry["avg_ms"] == 10.0


def test_observe_never_raises_on_garbage(caplog):
    with caplog.at_level(logging.DEBUG, logger="nextcloud_tools"):
        assert stats.observe(tool_name="nc_x", result=object(), duration_ms="not-a-number") is None
        assert stats.observe(tool_name="nc_x", result=None, duration_ms=None) is None
        assert stats.observe() is None
        assert stats.observe(tool_name=123) is None
    snap = stats.snapshot()
    assert snap["total_calls"] == 2  # the two nc_x calls counted; result unparseable -> ok


def test_snapshot_sorted_by_calls_desc():
    stats.observe(tool_name="nc_b", result='{"ok": true}', duration_ms=1)
    stats.observe(tool_name="nc_a", result='{"ok": true}', duration_ms=1)
    stats.observe(tool_name="nc_a", result='{"ok": true}', duration_ms=3)
    tools = stats.snapshot()["tools"]
    assert [t["tool"] for t in tools] == ["nc_a", "nc_b"]
    assert tools[0]["avg_ms"] == 2.0
