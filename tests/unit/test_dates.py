from datetime import date

from app.core.dates import (
    DateInterval,
    calculate_months_between,
    calculate_total_merged_months,
    format_months_to_years_and_months,
    is_open_ended,
    parse_date_range,
    parse_single_date,
)


def test_overlap_union_regression_case():
    """The exact proven regression case: two 36-month roles overlapping by
    12 months must union to 48 months, not 72."""
    total = calculate_total_merged_months([
        DateInterval(date(2020, 1, 1), date(2022, 12, 31)),
        DateInterval(date(2021, 1, 1), date(2023, 12, 31)),
    ])
    assert total == 48


def test_non_overlapping_consecutive_roles_sum_normally():
    total = calculate_total_merged_months([
        DateInterval(date(2018, 1, 1), date(2019, 12, 31)),
        DateInterval(date(2020, 1, 1), date(2021, 12, 31)),
    ])
    assert total == 48


def test_real_gap_between_roles_excludes_gap():
    total = calculate_total_merged_months([
        DateInterval(date(2018, 1, 1), date(2018, 12, 31)),
        DateInterval(date(2020, 1, 1), date(2020, 12, 31)),
    ])
    assert total == 24  # gap itself contributes 0


def test_calculate_months_between_same_month_is_one():
    assert calculate_months_between(date(2020, 1, 1), date(2020, 1, 31)) == 1


def test_calculate_months_between_end_before_start_is_zero():
    assert calculate_months_between(date(2020, 5, 1), date(2020, 1, 1)) == 0


def test_format_months_singular_plural():
    assert format_months_to_years_and_months(0) == "0 months"
    assert format_months_to_years_and_months(1) == "1 month"
    assert format_months_to_years_and_months(12) == "1 year"
    assert format_months_to_years_and_months(13) == "1 year 1 month"
    assert format_months_to_years_and_months(25) == "2 years 1 month"


def test_parse_single_date_month_name_year():
    assert parse_single_date("Jan 2020", is_end=False) == date(2020, 1, 1)
    assert parse_single_date("January 2020", is_end=False) == date(2020, 1, 1)
    assert parse_single_date("Jan 2020", is_end=True) == date(2020, 1, 31)


def test_parse_single_date_slash_format():
    assert parse_single_date("01/2020", is_end=False) == date(2020, 1, 1)


def test_parse_single_date_bare_year():
    assert parse_single_date("2020", is_end=False) == date(2020, 1, 1)
    assert parse_single_date("2020", is_end=True) == date(2020, 12, 31)


def test_parse_single_date_unparseable_returns_none():
    assert parse_single_date("not a date", is_end=False) is None


def test_is_open_ended():
    assert is_open_ended("Present")
    assert is_open_ended("Current")
    assert is_open_ended("Till Date")
    assert is_open_ended("till date")
    assert not is_open_ended("Jan 2020")


def test_parse_date_range_curly_apostrophe_two_digit_year():
    """Real format found in a live sample resume: "June'19 - Till date"."""
    today = date(2026, 8, 17)
    result = parse_date_range("June’19 - Till date", today=today)
    assert result.start == date(2019, 6, 1)
    assert result.end == today
    assert result.is_current is True


def test_parse_date_range_two_digit_years_both_sides():
    today = date(2026, 8, 17)
    result = parse_date_range("June’18 - Jan’19", today=today)
    assert result.start == date(2018, 6, 1)
    assert result.end == date(2019, 1, 31)
    assert result.is_current is False


def test_parse_date_range_standard_format():
    today = date(2026, 8, 17)
    result = parse_date_range("Jan 2020 - Present", today=today)
    assert result.start == date(2020, 1, 1)
    assert result.is_current is True
