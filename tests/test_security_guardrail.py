"""Guardrail hardening: non-GET nc_ocs methods gate as writes (review S2)."""


def test_guard_nc_ocs_method_gating(fake_ctx):
    from nextcloud_tools import guardrails

    assert guardrails.guard("nc_ocs", {"method": "GET", "path": "x"}) is None
    assert guardrails.guard("nc_ocs", {"path": "x"}) is None  # default GET
    for m in ("POST", "PUT", "patch"):
        w = guardrails.guard("nc_ocs", {"method": m, "path": "x"})
        assert w["action"] == "approve" and w["rule_key"] == "nc-write", m
    d = guardrails.guard("nc_ocs", {"method": "DELETE", "path": "x"})
    assert d["action"] == "approve" and d["rule_key"] == "nc-destructive"
    assert "DELETE /ocs/v2.php/x (destructive)" in d["message"]
