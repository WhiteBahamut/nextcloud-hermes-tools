from datetime import datetime

from nextcloud_tools import ical, tools_cal, vcard


def test_unfold_and_parse_content_line():
    comps = ical.parse_ics(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:u\r\n"
        "SUMMARY:Long value folded\r\n  across lines\r\n"
        "DTSTART;VALUE=DATE:20261224\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    ev = ical.first_component(comps, "VEVENT")
    assert ical.prop(ev, "SUMMARY") == "Long value folded across lines"
    params, value = ical.prop_with_params(ev, "DTSTART")
    assert params == {"VALUE": "DATE"} and value == "20261224"


def test_parse_dt_variants():
    assert ical.parse_dt("20261224", {"VALUE": "DATE"}) == datetime(2026, 12, 24)
    assert ical.parse_dt("20261110T140000Z").tzinfo is not None
    assert ical.parse_dt("20261110T140000") == datetime(2026, 11, 10, 14)
    assert ical.parse_iso("2026-11-07T10:00:00+01:00") is not None
    assert ical.parse_iso("2026-11-07") == datetime(2026, 11, 7)


def test_build_vevent_escapes_and_folds():
    text = ical.build_vevent(summary="a,b;c\nd", start=datetime(2026, 1, 1, 10), end=datetime(2026, 1, 1, 11))
    assert "SUMMARY:a\\,b\\;c\\nd" in text
    assert "BEGIN:VCALENDAR" in text and "END:VCALENDAR" in text
    assert all(len(line.encode()) <= 75 or line.startswith(" ") for line in text.split("\r\n"))


def test_build_vtodo_needs_action():
    text = ical.build_vtodo(summary="T", due="2026-11-20", priority=3)
    assert "STATUS:NEEDS-ACTION" in text and "DUE;VALUE=DATE:20261120" in text and "PRIORITY:3" in text


def test_build_vtodo_status():
    text = ical.build_vtodo(summary="T", status="cancelled")
    assert "STATUS:CANCELLED" in text and "COMPLETED:" not in text and "PERCENT-COMPLETE" not in text
    done = ical.build_vtodo(summary="T", status="COMPLETED")
    assert "STATUS:COMPLETED" in done and "PERCENT-COMPLETE:100" in done and "COMPLETED:" in done


def test_rrule_unsupported_freq_single_occurrence():
    occ = ical.expand_rrule(datetime(2026, 1, 1, 9), "FREQ=YEARLY;COUNT=5")
    assert occ == [datetime(2026, 1, 1, 9)]


def test_parse_duration_and_fmt_duration_roundtrip():
    from datetime import timedelta

    assert ical.parse_duration("-PT15M") == timedelta(minutes=-15)
    assert ical.fmt_duration(ical.parse_duration("-PT15M")) == "-PT15M"
    assert ical.fmt_duration(ical.parse_duration("P1D")) == "P1D"
    assert ical.fmt_duration(ical.parse_duration("PT1H30M")) == "PT1H30M"
    assert ical.fmt_duration(ical.parse_duration("P1W")) == "P1W"
    assert ical.fmt_duration(ical.parse_duration("-p1dt2h")) == "-P1DT2H"  # case-insensitive
    assert ical.fmt_duration(timedelta(0)) == "PT0S"
    for bad in ("P", "15M", "", "PT", "P1DT", "abc"):
        try:
            ical.parse_duration(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"parse_duration({bad!r}) must raise ValueError")


def test_build_vevent_reminder_valarm():
    text = ical.build_vevent(summary="Meet", start=datetime(2026, 1, 1, 10), end=datetime(2026, 1, 1, 11), reminder="-PT15M")
    assert "BEGIN:VALARM" in text and "ACTION:DISPLAY" in text
    assert "TRIGGER:-PT15M" in text and "DESCRIPTION:Meet" in text
    assert text.index("BEGIN:VALARM") < text.index("END:VEVENT")
    plain = ical.build_vevent(summary="Meet", start=datetime(2026, 1, 1, 10), end=datetime(2026, 1, 1, 11))
    assert "VALARM" not in plain


def test_vcard_cdata_and_params():
    raw = "<![CDATA[BEGIN:VCARD\r\nVERSION:4.0\r\nUID:u\r\nFN:A\r\nTEL;TYPE=WORK,VOICE:+1\r\nEND:VCARD]]>"
    card = vcard.parse_vcard(raw)
    assert card["phones"] == ["+1"] and card["fn"] == "A"


def test_vcard_build_has_required_fn_and_uid():
    text = vcard.build_vcard(fn="X")
    card = vcard.parse_vcard(text)
    assert card["fn"] == "X" and card["uid"]  # uuid4 generated
    assert "VERSION:4.0" in text


def test_fmt_dt_passthrough_no_conversion():
    from datetime import timedelta, timezone as tz
    assert ical.fmt_dt(datetime(2026, 11, 10, 14, tzinfo=tz.utc))[0] == "20261110T140000Z"
    plus2 = datetime(2026, 11, 10, 14, tzinfo=tz(timedelta(hours=2)))
    assert ical.fmt_dt(plus2)[0] == "20261110T140000"  # wall time kept, no conversion to 120000Z
    assert ical.fmt_dt(datetime(2026, 11, 10, 14))[0] == "20261110T140000"


def test_is_date_only_and_dt_style():
    from datetime import timedelta, timezone as tz

    assert ical.is_date_only("2026-11-20") is True
    assert ical.is_date_only("2026-11-20T00:00:00") is False
    assert ical.dt_style(datetime(2026, 11, 16, 9, tzinfo=tz.utc)) == "z"
    assert ical.dt_style(datetime(2026, 11, 16, 9, tzinfo=tz(timedelta(hours=2)))) == "offset"
    assert ical.dt_style(datetime(2026, 11, 16, 9)) == "floating"


# --- component stack (VALARM) ---


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


# --- RRULE expansion (ical.expand_rrule) ---


def test_rrule_daily_count():
    occ = ical.expand_rrule(datetime(2026, 11, 2, 9), "FREQ=DAILY;COUNT=3")
    assert [o.day for o in occ] == [2, 3, 4]


def test_rrule_daily_interval():
    occ = ical.expand_rrule(datetime(2026, 11, 2, 9), "FREQ=DAILY;INTERVAL=2;COUNT=3")
    assert [o.day for o in occ] == [2, 4, 6]


def test_rrule_weekly_byday():
    # 2026-11-02 is a Monday
    occ = ical.expand_rrule(datetime(2026, 11, 2, 9), "FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4")
    assert [o.strftime("%a") for o in occ] == ["Mon", "Wed", "Mon", "Wed"]


def test_rrule_monthly_until_skips_invalid_days():
    occ = ical.expand_rrule(datetime(2026, 1, 31, 9), "FREQ=MONTHLY;UNTIL=20260430T235959Z")
    assert [o.date().isoformat() for o in occ] == ["2026-01-31", "2026-03-31"]  # Feb 31 / Apr 31 skipped


def test_rrule_exdate_and_range_filter():
    occ = ical.expand_rrule(
        datetime(2026, 11, 2, 9), "FREQ=DAILY;COUNT=5",
        range_start=datetime(2026, 11, 3), range_end=datetime(2026, 11, 5, 23, 59),
        exdates=[({}, "20261104T090000")],
    )
    assert [o.day for o in occ] == [3, 5]  # 4th excluded via EXDATE


def test_rrule_exdate_from_parse_ics():
    # regression: parse_ics stores props as (params, value); expand_rrule must unpack in that order
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x1\r\nDTSTAMP:20261101T000000Z\r\n"
        "DTSTART;TZID=Europe/Berlin:20261102T090000\r\nDTEND;TZID=Europe/Berlin:20261102T100000\r\n"
        "RRULE:FREQ=DAILY;COUNT=5\r\nEXDATE;TZID=Europe/Berlin:20261104T090000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    vevent = ical.first_component(ical.parse_ics(ics), "VEVENT")
    dt_p, dt_v = ical.prop_with_params(vevent, "DTSTART")
    occ = ical.expand_rrule(
        ical.parse_dt(dt_v, dt_p),
        ical.prop(vevent, "RRULE"),
        exdates=vevent["props"]["EXDATE"],
    )
    assert [o.day for o in occ] == [2, 3, 5, 6]  # 4th excluded, no exception


def test_event_dict_exdate_end_to_end():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:x2\r\nDTSTAMP:20261101T000000Z\r\n"
        "DTSTART:20261102T090000Z\r\nDTEND:20261102T100000Z\r\n"
        "RRULE:FREQ=DAILY;COUNT=4\r\nEXDATE:20261104T090000Z\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    vevent = ical.first_component(ical.parse_ics(ics), "VEVENT")
    ev = tools_cal._event_dict(vevent, None, None)
    assert [o["start"][:10] for o in ev["occurrences"]] == ["2026-11-02", "2026-11-03", "2026-11-05"]


def test_rrule_capped_at_500():
    occ = ical.expand_rrule(datetime(2026, 1, 1, 9), "FREQ=DAILY", range_end=datetime(2030, 1, 1))
    assert len(occ) == 500


# --- vcard edge cases ---


def test_vcard_unfold_cdata_group_prefix():
    raw = (
        "<![CDATA[BEGIN:VCARD\r\nVERSION:4.0\r\nUID:u9\r\nFN:J\xc3\xb6rg M\xc3\xbcller\r\n"
        "item1.EMAIL:a@b.c\r\nTEL;TYPE=CELL:+49 30\r\nORG:Acme\\;HQ\r\nEND:VCARD]]>"
    ).encode("latin-1").decode("utf-8")
    card = vcard.parse_vcard(raw)
    assert card["uid"] == "u9"
    assert card["emails"] == ["a@b.c"]  # group prefix item1. normalized away
    assert card["phones"] == ["+49 30"]
    assert card["org"] == "Acme\\;HQ"


def test_vcard_folded_line_unfolds():
    raw = "BEGIN:VCARD\r\nVERSION:4.0\r\nUID:u\r\nFN:Very Long Name That Was Fold\r\n ed Across Lines\r\nEND:VCARD\r\n"
    card = vcard.parse_vcard(raw)
    assert card["fn"] == "Very Long Name That Was Folded Across Lines"


def test_build_vcard_roundtrip_utf8():
    text = vcard.build_vcard(fn="Müller, Jörg", email="j@x.de", phone="+49", uid="u1")
    card = vcard.parse_vcard(text)
    assert card["fn"] == "Müller\\, Jörg"  # escaped on build; non-ASCII preserved as UTF-8
    assert card["uid"] == "u1" and card["emails"] == ["j@x.de"]
    assert "VERSION:4.0" in text and "FN:" in text
