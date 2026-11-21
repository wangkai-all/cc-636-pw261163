from __future__ import annotations

from datetime import datetime

import pytest

from app.timecodes import (
    SPSS_EPOCH,
    STATA_EPOCH,
    interpret_value,
    parse_time_spec,
)


def test_spss_date_uses_1582_epoch():
    spec = parse_time_spec("DATE11", "double")
    assert spec is not None and spec.supported
    raw = (datetime(2020, 1, 1) - SPSS_EPOCH).total_seconds()
    result = interpret_value(raw, spec)
    assert result.analysis_state == "ok"
    assert result.analysis == "2020-01-01"
    assert result.label == "2020-01-01"


def test_spss_datetime_and_partial_formats():
    spec = parse_time_spec("DATETIME20", "double")
    raw = (datetime(2020, 1, 1, 8, 30, 15) - SPSS_EPOCH).total_seconds()
    result = interpret_value(raw, spec)
    assert result.analysis == "2020-01-01T08:30:15"

    month = parse_time_spec("MOYR8", "double")
    result = interpret_value(raw, month)
    assert result.label == "2020-01"


def test_spss_duration_is_not_a_calendar_date():
    spec = parse_time_spec("MTIME10", "double")
    result = interpret_value(125.5, spec)
    assert result.analysis_state == "ok"
    assert result.analysis == 125.5
    assert "时长" in result.notes[0]


def test_stata_epochs_and_units():
    td = parse_time_spec("%td", "double")
    assert interpret_value((datetime(2020, 1, 1) - STATA_EPOCH).days, td).analysis == "2020-01-01"

    tc = parse_time_spec("%tc", "double")
    raw = (datetime(2020, 1, 1, 8, 30, 15) - STATA_EPOCH).total_seconds() * 1000
    assert interpret_value(raw, tc).analysis == "2020-01-01T08:30:15"

    tm = parse_time_spec("%tm", "double")
    assert interpret_value((2020 - 1960) * 12, tm).label == "2020m1"
    assert interpret_value((2020 - 1960) * 12, tm).analysis == "2020-01-01"

    tq = parse_time_spec("%tq", "double")
    assert interpret_value((2020 - 1960) * 4, tq).label == "2020q1"

    th = parse_time_spec("%th", "double")
    assert interpret_value((2020 - 1960) * 2, th).label == "2020h1"

    ty = parse_time_spec("%ty", "double")
    assert interpret_value(2020, ty).analysis == 2020


def test_stata_fractional_day_keeps_time():
    td = parse_time_spec("%td", "double")
    result = interpret_value(21915.5, td)
    assert result.analysis == "2020-01-01T12:00:00"


@pytest.mark.parametrize("fmt", ["%tw", "%tb", "%tg"])
def test_unsupported_stata_formats_are_refused(fmt):
    spec = parse_time_spec(fmt, "double")
    assert spec is not None and not spec.supported
    result = interpret_value(12, spec)
    assert result.analysis_state == "unsupported"
    assert result.analysis is None
    assert spec.reason


def test_unknown_spss_format_is_refused_not_guessed():
    spec = parse_time_spec("MYSTERY9", "double")
    assert spec is not None and not spec.supported
    assert interpret_value(42, spec).analysis_state == "unsupported"


def test_plain_numeric_format_is_not_temporal():
    assert parse_time_spec("F8.2", "double") is None
    assert parse_time_spec("A20", "string") is None
    assert parse_time_spec(None, "double") is None


def test_out_of_range_seconds_are_reported():
    spec = parse_time_spec("DATE11", "double")
    result = interpret_value(1e18, spec)
    assert result.analysis_state == "out_of_range"
    assert result.analysis is None
