"""Schema hygiene: every NC_* schema property carries a non-empty description."""

from nextcloud_tools import schemas


def test_every_schema_property_has_description():
    checked = 0
    for name in sorted(dir(schemas)):
        if not name.startswith("NC_"):
            continue
        schema = getattr(schemas, name)
        props = schema["parameters"]["properties"]
        for prop, spec in props.items():
            assert isinstance(spec, dict) and spec.get("description"), (
                f"{name}.{prop} is missing a description"
            )
            checked += 1
    assert checked > 100  # guard against the sweep silently matching nothing


def test_every_tool_description_is_short():
    checked = 0
    for name in sorted(dir(schemas)):
        if not name.startswith("NC_"):
            continue
        description = getattr(schemas, name)["description"]
        assert isinstance(description, str) and 0 < len(description) <= 140, (
            f"{name} description must be a non-empty string of at most 140 chars"
        )
        checked += 1
    assert checked == 52  # guard against the sweep silently matching the wrong set
