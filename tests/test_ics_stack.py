"""ICS parsing keeps a component stack so VALARM doesn't drop VEVENT props (review S6)."""


def test_parse_ics_valarm_does_not_drop_parent_props():
    from nextcloud_tools import ical

    comps = ical.parse_ics(
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:u1\r\nSUMMARY:Before\r\n"
        "BEGIN:VALARM\r\nACTION:DISPLAY\r\nEND:VALARM\r\n"
        "DESCRIPTION:After alarm\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    vevent = ical.first_component(comps, "VEVENT")
    assert ical.prop(vevent, "UID") == "u1"
    assert ical.prop(vevent, "SUMMARY") == "Before"
    assert ical.prop(vevent, "DESCRIPTION") == "After alarm"
    alarm = ical.first_component(comps, "VALARM")  # flat list shape preserved
    assert alarm is not None and ical.prop(alarm, "ACTION") == "DISPLAY"


def test_parse_ics_nests_valarm_in_parent_components():
    from nextcloud_tools import ical

    comps = ical.parse_ics(
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:u2\r\nSUMMARY:S\r\n"
        "BEGIN:VALARM\r\nACTION:DISPLAY\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    vevent = ical.first_component(comps, "VEVENT")
    assert len(vevent["components"]) == 1
    alarm = vevent["components"][0]
    assert alarm["type"] == "VALARM" and ical.prop(alarm, "TRIGGER") == "-PT15M"
    assert ical.first_component(comps, "VALARM") is alarm  # still in the flat list


def test_serialize_component_emits_nested_valarm_roundtrip():
    from nextcloud_tools import ical

    text = (
        "BEGIN:VEVENT\r\nUID:u3\r\nSUMMARY:S\r\n"
        "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:D\r\nTRIGGER:-PT5M\r\nEND:VALARM\r\n"
        "END:VEVENT\r\n"
    )
    vevent = ical.first_component(ical.parse_ics(text), "VEVENT")
    out = ical.serialize_component(vevent)
    assert out.index("BEGIN:VALARM") < out.index("END:VALARM") < out.index("END:VEVENT")
    reparsed = ical.first_component(ical.parse_ics("\r\n".join(out)), "VEVENT")
    assert len(reparsed["components"]) == 1
    assert ical.prop(reparsed["components"][0], "TRIGGER") == "-PT5M"
