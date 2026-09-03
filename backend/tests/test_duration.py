from app.scrapers.duration import classify_youtube_format, parse_iso8601_duration


def test_parse_iso8601_duration():
    assert parse_iso8601_duration("PT45S") == 45
    assert parse_iso8601_duration("PT12M34S") == 754
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_iso8601_duration("PT58S") == 58
    assert parse_iso8601_duration("PT24M7S") == 1447


def test_parse_iso8601_duration_edge_cases():
    assert parse_iso8601_duration("") == 0
    assert parse_iso8601_duration("P0D") == 0
    assert parse_iso8601_duration("not a duration") == 0
    assert parse_iso8601_duration("PT1H") == 3600
    assert parse_iso8601_duration("PT5M") == 300


def test_classify_youtube_format():
    assert classify_youtube_format(58) == "short"
    assert classify_youtube_format(180) == "short"
    assert classify_youtube_format(181) == "long"
    assert classify_youtube_format(754) == "long"
