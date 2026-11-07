import pytest

from nextcloud_tools import dashboard_store


def test_list_tool_names_returns_43_in_manifest_order():
    names = dashboard_store.list_tool_names()
    assert len(names) == 43
    assert names[0] == "nc_file_list"
    assert names[-1] == "nc_ocs"
    assert all(n.startswith("nc_") for n in names)


def test_get_disabled_tools_tolerates_missing_or_wrong_typed_sections():
    assert dashboard_store.get_disabled_tools({}) == []
    assert dashboard_store.get_disabled_tools({"plugins": None}) == []
    assert dashboard_store.get_disabled_tools({"plugins": {"entries": None}}) == []
    cfg = {"plugins": {"entries": {"nextcloud-tools": {"settings": None}}}}
    assert dashboard_store.get_disabled_tools(cfg) == []
    cfg = {"plugins": {"entries": {"nextcloud-tools": {"settings": {"disabled_tools": "oops"}}}}}
    assert dashboard_store.get_disabled_tools(cfg) == []


def test_get_disabled_tools_reads_nested_list():
    cfg = {"plugins": {"entries": {"nextcloud-tools": {"settings": {"disabled_tools": ["nc_file_delete"]}}}}}
    assert dashboard_store.get_disabled_tools(cfg) == ["nc_file_delete"]


def test_set_tool_enabled_roundtrip_sorted_idempotent():
    config = {}
    assert dashboard_store.set_tool_enabled(config, "nc_file_delete", False) == ["nc_file_delete"]
    assert config["plugins"]["entries"]["nextcloud-tools"]["settings"]["disabled_tools"] == [
        "nc_file_delete"
    ]
    # second disable keeps the list sorted
    assert dashboard_store.set_tool_enabled(config, "nc_cal_delete", False) == [
        "nc_cal_delete",
        "nc_file_delete",
    ]
    # idempotent
    assert dashboard_store.set_tool_enabled(config, "nc_cal_delete", False) == [
        "nc_cal_delete",
        "nc_file_delete",
    ]
    # enable removes
    assert dashboard_store.set_tool_enabled(config, "nc_file_delete", True) == ["nc_cal_delete"]
    assert dashboard_store.set_tool_enabled(config, "nc_cal_delete", True) == []
    # enabling a never-disabled tool is a no-op
    assert dashboard_store.set_tool_enabled(config, "nc_file_list", True) == []


def test_set_tool_enabled_rejects_unknown_name_before_mutating():
    config = {}
    with pytest.raises(ValueError):
        dashboard_store.set_tool_enabled(config, "nc_not_a_tool", False)
    assert config == {}


def test_set_tool_enabled_preserves_sibling_settings():
    config = {
        "plugins": {
            "entries": {
                "nextcloud-tools": {"settings": {"max_results": 5, "disabled_tools": ["nc_ocs"]}}
            }
        }
    }
    assert dashboard_store.set_tool_enabled(config, "nc_ocs", True) == []
    settings = config["plugins"]["entries"]["nextcloud-tools"]["settings"]
    assert settings["max_results"] == 5
    assert settings["disabled_tools"] == []


def test_classify_gate_static_labels():
    assert dashboard_store.classify_gate("nc_file_list") == "read"
    assert dashboard_store.classify_gate("nc_file_put") == "write"
    assert dashboard_store.classify_gate("nc_file_delete") == "destructive"
    assert dashboard_store.classify_gate("nc_comments") == "mixed"
    assert dashboard_store.classify_gate("nc_ocs") == "mixed"


def test_classify_gate_covers_every_manifest_tool():
    mixed = {"nc_comments", "nc_ocs"}
    for name in dashboard_store.list_tool_names():
        gate = dashboard_store.classify_gate(name)
        assert gate in ("read", "write", "destructive", "mixed"), name
        if name in mixed:
            assert gate == "mixed", name
        else:
            assert gate != "mixed", name
