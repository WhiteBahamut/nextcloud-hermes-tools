import pytest

from nextcloud_tools import dashboard_store, schemas


def test_list_tool_names_returns_52_in_manifest_order():
    names = dashboard_store.list_tool_names()
    assert len(names) == 52
    assert names[0] == "nc_file_list"
    assert names[-1] == "nc_version"
    assert all(n.startswith("nc_") for n in names)


@pytest.mark.parametrize("getter,key", [
    (dashboard_store.get_disabled_tools, "disabled_tools"),
    (dashboard_store.get_ungated_tools, "ungated_tools"),
])
def test_get_tools_tolerates_missing_or_wrong_typed_sections(getter, key):
    assert getter({}) == []
    assert getter({"plugins": None}) == []
    assert getter({"plugins": {"entries": None}}) == []
    cfg = {"plugins": {"entries": {"nextcloud-tools": {"settings": None}}}}
    assert getter(cfg) == []
    cfg = {"plugins": {"entries": {"nextcloud-tools": {"settings": {key: "oops"}}}}}
    assert getter(cfg) == []


@pytest.mark.parametrize("getter,key,sample", [
    (dashboard_store.get_disabled_tools, "disabled_tools", "nc_file_delete"),
    (dashboard_store.get_ungated_tools, "ungated_tools", "nc_file_put"),
])
def test_get_tools_reads_nested_list(getter, key, sample):
    cfg = {"plugins": {"entries": {"nextcloud-tools": {"settings": {key: [sample]}}}}}
    assert getter(cfg) == [sample]


@pytest.mark.parametrize("setter,key,first", [
    (dashboard_store.set_tool_enabled, "disabled_tools", "nc_file_delete"),
    (dashboard_store.set_tool_guarded, "ungated_tools", "nc_file_put"),
])
def test_set_tool_flag_roundtrip_sorted_idempotent(setter, key, first):
    config = {}
    assert setter(config, first, False) == [first]
    assert config["plugins"]["entries"]["nextcloud-tools"]["settings"][key] == [first]
    # second call keeps the list sorted
    assert setter(config, "nc_cal_delete", False) == ["nc_cal_delete", first]
    # idempotent
    assert setter(config, "nc_cal_delete", False) == ["nc_cal_delete", first]
    # re-enabling removes
    assert setter(config, first, True) == ["nc_cal_delete"]
    assert setter(config, "nc_cal_delete", True) == []
    # enabling a never-disabled tool is a no-op
    assert setter(config, "nc_file_list", True) == []


@pytest.mark.parametrize("setter,key", [
    (dashboard_store.set_tool_enabled, "disabled_tools"),
    (dashboard_store.set_tool_guarded, "ungated_tools"),
])
def test_set_tool_flag_rejects_unknown_name_before_mutating(setter, key):
    config = {}
    with pytest.raises(ValueError):
        setter(config, "nc_not_a_tool", False)
    assert config == {}


@pytest.mark.parametrize("setter,key", [
    (dashboard_store.set_tool_enabled, "disabled_tools"),
    (dashboard_store.set_tool_guarded, "ungated_tools"),
])
def test_set_tool_flag_preserves_sibling_settings(setter, key):
    config = {
        "plugins": {
            "entries": {
                "nextcloud-tools": {"settings": {"max_results": 5, key: ["nc_ocs"]}}
            }
        }
    }
    assert setter(config, "nc_ocs", True) == []
    settings = config["plugins"]["entries"]["nextcloud-tools"]["settings"]
    assert settings["max_results"] == 5
    assert settings[key] == []


def test_classify_gate_static_labels():
    assert dashboard_store.classify_gate("nc_file_list") == "read"
    assert dashboard_store.classify_gate("nc_file_put") == "write"
    assert dashboard_store.classify_gate("nc_file_delete") == "destructive"
    assert dashboard_store.classify_gate("nc_comment_list") == "read"
    assert dashboard_store.classify_gate("nc_comment_add") == "write"
    assert dashboard_store.classify_gate("nc_comment_delete") == "destructive"
    assert dashboard_store.classify_gate("nc_ocs") == "mixed"


def test_classify_gate_covers_every_manifest_tool():
    mixed = {"nc_ocs"}
    for name in dashboard_store.list_tool_names():
        gate = dashboard_store.classify_gate(name)
        assert gate in ("read", "write", "destructive", "mixed"), name
        if name in mixed:
            assert gate == "mixed", name
        else:
            assert gate != "mixed", name


def test_tool_doc_known_tool_returns_live_schema():
    doc = dashboard_store.tool_doc("nc_file_put")
    assert doc["description"] == schemas.NC_FILE_PUT["description"]
    params = doc["parameters"]
    assert params is schemas.NC_FILE_PUT["parameters"]  # same object — no duplicated text
    assert params["type"] == "object"
    assert params["required"] == ["path"]
    assert set(params["properties"]) == {"path", "content", "content_base64", "content_type", "allow_empty"}


def test_tool_doc_unknown_name_returns_empty_shape():
    assert dashboard_store.tool_doc("nc_not_a_tool") == {
        "description": "",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }


def test_tool_doc_covers_every_manifest_tool():
    checked = 0
    for name in dashboard_store.list_tool_names():
        doc = dashboard_store.tool_doc(name)
        assert isinstance(doc["description"], str) and doc["description"], name
        params = doc["parameters"]
        assert isinstance(params, dict) and isinstance(params.get("properties"), dict), name
        checked += 1
    assert checked == 52  # guard against the sweep silently matching nothing
