"""
Deterministic date parsing/duration math (spec §30/§32 -- "No LLM date
arithmetic"). Ported and extended from the proven C# DateNormalizer/
DateCalculator (via the prior Python port's date_calculator.py): same
interval-union overlap-merge logic, verified against that system's own
regression case (two 1-year-overlapping 36-month roles must union to 48
months, not 72). Extended here to handle a real pattern found in the sample
resume this pipeline was smoke-tested against: 2-digit years and a curly
apostrophe before the year ("June'19", using U+2019 not ASCII ' ).
"""
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_OPEN_END_WORDS = re.compile(r"\b(present|current|till\s*date|now|ongoing)\b", re.IGNORECASE)

_MONTH_NAME_YEAR = re.compile(
    r"(?P<m>[A-Za-z]{3,9})\.?\s*[’']?\s*(?P<y>\d{4}|\d{2})\b"
)
_SLASH_MY = re.compile(r"\b(?P<m>\d{1,2})[/.\-](?P<y>\d{4})\b")
_SLASH_YM = re.compile(r"\b(?P<y>\d{4})[/.\-](?P<m>\d{1,2})\b")
_BARE_YEAR = re.compile(r"\b(?P<y>19\d{2}|20\d{2})\b")

_RANGE_SPLIT = re.compile(r"\s*(?:–|—|-|\bto\b)\s*", re.IGNORECASE)


def _resolve_year(raw: str) -> int:
    y = int(raw)
    if y < 100:
        # 2-digit year -- resumes using this convention always mean 2000s.
        return 2000 + y
    return y


def _month_from_name(name: str) -> int | None:
    key = name[:3].lower()
    return _MONTHS.get(key)


def parse_single_date(text: str, *, is_end: bool) -> date | None:
    """Parses one date expression to a `date` -- start dates resolve to the
    1st of the month, end dates to the last day of the month (so duration
    math is inclusive of the whole month), bare years resolve to Jan 1 /
    Dec 31. Returns None (never today's date) when nothing parses -- the
    "Present/Current/Till date" -> today resolution is the caller's job via
    is_open_ended(), kept separate so this function stays pure/testable."""
    if not text or not text.strip():
        return None
    trimmed = text.strip()

    m = _MONTH_NAME_YEAR.search(trimmed)
    if m and _month_from_name(m.group("m")) is not None:
        month = _month_from_name(m.group("m"))
        year = _resolve_year(m.group("y"))
        day = 1 if not is_end else monthrange(year, month)[1]
        return date(year, month, day)

    m = _SLASH_MY.search(trimmed)
    if m:
        month = int(m.group("m"))
        if 1 <= month <= 12:
            year = _resolve_year(m.group("y"))
            day = 1 if not is_end else monthrange(year, month)[1]
            return date(year, month, day)

    m = _SLASH_YM.search(trimmed)
    if m:
        month = int(m.group("m"))
        if 1 <= month <= 12:
            year = _resolve_year(m.group("y"))
            day = 1 if not is_end else monthrange(year, month)[1]
            return date(year, month, day)

    m = _BARE_YEAR.search(trimmed)
    if m:
        year = int(m.group("y"))
        return date(year, 1, 1) if not is_end else date(year, 12, 31)

    return None


def is_open_ended(text: str) -> bool:
    return bool(text and _OPEN_END_WORDS.search(text))


@dataclass
class ParsedDateRange:
    start: date | None
    end: date | None
    is_current: bool


def parse_date_range(range_text: str, *, today: date) -> ParsedDateRange:
    """Splits a combined range string ("Jan 2020 - Mar 2023", "June'19 -
    Till date") and resolves both sides. An open-ended end resolves to
    `today` (passed in, never computed here, so this stays pure/testable and
    never silently uses a stale "now")."""
    if not range_text or not range_text.strip():
        return ParsedDateRange(None, None, False)

    parts = _RANGE_SPLIT.split(range_text.strip(), maxsplit=1)
    if len(parts) == 2:
        start_str, end_str = parts
    else:
        start_str, end_str = range_text.strip(), ""

    start = parse_single_date(start_str, is_end=False)
    is_current = is_open_ended(end_str) or not end_str.strip()
    end = today if is_current else parse_single_date(end_str, is_end=True)

    if end is None and start is not None:
        # Genuinely unparseable end (not caught by is_open_ended) --
        # matches the C# fallback: treat as open/current rather than
        # dropping the role's end boundary entirely.
        end = today
        is_current = True

    if start is not None and end is not None and end < start and start.year == end.year:
        # Same-year typo correction ported from DateNormalizer.
        end = date(start.year, min(start.month + 1, 12), 28)

    return ParsedDateRange(start=start, end=end, is_current=is_current)


def calculate_months_between(start: date, end: date) -> int:
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    return max(1, months)


@dataclass
class DateInterval:
    start: date
    end: date


def calculate_total_merged_months(ranges: list[DateInterval]) -> int:
    """Interval-union overlap merge -- verified against the C# suite's own
    regression case: Jan2020-Dec2022 (36mo) union Jan2021-Dec2023 (36mo),
    overlapping by 1 year, must total 48 months, not 72."""
    valid = sorted((r for r in ranges if r.start <= r.end), key=lambda r: r.start)
    if not valid:
        return 0

    merged: list[DateInterval] = [DateInterval(valid[0].start, valid[0].end)]
    for r in valid[1:]:
        current = merged[-1]
        # +1 day tolerance lets a Dec 31 -> Jan 1 back-to-back pair merge as
        # one continuous span (contiguous, not just overlapping).
        if r.start <= _add_days(current.end, 1):
            if r.end > current.end:
                current.end = r.end
        else:
            merged.append(DateInterval(r.start, r.end))

    return sum(calculate_months_between(r.start, r.end) for r in merged)


def _add_days(d: date, days: int) -> date:
    from datetime import timedelta

    return d + timedelta(days=days)


def format_months_to_years_and_months(total_months: int) -> str:
    if total_months <= 0:
        return "0 months"
    years, months = divmod(total_months, 12)
    if years == 0:
        return f"{months} month" + ("" if months == 1 else "s")
    if months == 0:
        return f"{years} year" + ("" if years == 1 else "s")
    return f"{years} year{'' if years == 1 else 's'} {months} month{'' if months == 1 else 's'}"
