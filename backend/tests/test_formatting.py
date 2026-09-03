from app.formatting import format_count, format_duration, initials_from_name, normalize_handle


def test_format_count_scales():
    assert format_count(950) == "950"
    assert format_count(4_200) == "4.2K"
    assert format_count(890_000) == "890K"
    assert format_count(18_200_000) == "18.2M"
    assert format_count(1_000_000) == "1M"
    assert format_count(2_500_000_000) == "2.5B"


def test_format_count_none_and_negative():
    assert format_count(None) == "—"
    assert format_count(-5_000) == "-5K"


def test_format_duration_variants():
    assert format_duration(45) == "0:45"
    assert format_duration(58) == "0:58"
    assert format_duration(754) == "12:34"
    assert format_duration(3723) == "1:02:03"
    assert format_duration(0) == "0:00"
    assert format_duration(None) == "0:00"


def test_initials_from_name():
    assert initials_from_name("Marques Brownlee") == "MB"
    assert initials_from_name("linustech") == "LI"
    assert initials_from_name("") == "??"
    assert initials_from_name("   ") == "??"
    assert initials_from_name("Dave2D Extra Words") == "DE"


def test_normalize_handle():
    assert normalize_handle("@mkbhd", "youtube") == "mkbhd"
    assert normalize_handle("mkbhd", "youtube") == "mkbhd"
    assert normalize_handle(" @mkbhd ", "youtube") == "mkbhd"
    assert normalize_handle("https://instagram.com/theverge/", "instagram") == "theverge"
    assert normalize_handle("@theverge", "instagram") == "theverge"
