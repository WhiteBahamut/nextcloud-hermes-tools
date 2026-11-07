"""nc_search queries providers concurrently, preserving order and per-provider errors (review P2)."""

import threading
import time

from conftest import ocs_err, ocs_ok


def test_search_providers_run_concurrently_and_keep_order(nc, call):
    state = {"cur": 0, "max": 0}
    lock = threading.Lock()

    def h(req):
        with lock:
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
        time.sleep(0.05)
        with lock:
            state["cur"] -= 1
        if "deck" in req.url.path:
            return ocs_err(404, "provider not installed")
        return ocs_ok([{"id": "1", "name": "hit"}])

    nc.handler = h
    res = call("nc_search", {"term": "x", "providers": ["files", "fulltextsearch", "deck"], "limit": 5})
    assert res["ok"] and res["count"] == 3
    assert state["max"] > 1  # requests actually overlapped
    assert [r["provider"] for r in res["results"]] == ["files", "fulltextsearch", "deck"]
    assert "error" in res["results"][2]  # per-provider error entry preserved
