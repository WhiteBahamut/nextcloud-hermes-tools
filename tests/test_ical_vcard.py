from datetime import datetime

from nextcloud_tools import ical, vcard


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


def test_rrule_unsupported_freq_single_occurrence():
    occ = ical.expand_rrule(datetime(2026, 1, 1, 9), "FREQ=YEARLY;COUNT=5")
    assert occ == [datetime(2026, 1, 1, 9)]


def test_vcard_cdata_and_params():
    raw = "<![CDATA[BEGIN:VCARD\r\nVERSION:4.0\r\nUID:u\r\nFN:A\r\nTEL;TYPE=WORK,VOICE:+1\r\nEND:VCARD]]>"
    card = vcard.parse_vcard(raw)
    assert card["phones"] == ["+1"] and card["fn"] == "A"


def test_vcard_build_has_required_fn_and_uid():
    text = vcard.build_vcard(fn="X")
    card = vcard.parse_vcard(text)
    assert card["fn"] == "X" and card["uid"]  # uuid4 generated
    assert "VERSION:4.0" in text
