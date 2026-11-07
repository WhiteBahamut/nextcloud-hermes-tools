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
