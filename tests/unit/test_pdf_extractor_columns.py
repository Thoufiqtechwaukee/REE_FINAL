"""
Column-detection regressions. The bug these guard: grouping words into lines
by Y position alone spliced a two-column resume's columns together, producing
"EDUCATION SKILLS" as one line -- the SKILLS pattern won, the Education
section ceased to exist, and a right-column heading landed mid-way through
the left column's Experience content, shredding the employment history. That
resume scored 0/25 on both Experience and Growth.

The false-positive guard matters just as much as the fix: splitting a
single-column page would break role lines that carry a right-aligned date
("Backend Developer Intern .... May 2024 - Jul 2024"), which is exactly what
_chunk_experience anchors roles on.
"""
from app.extraction import pdf_extractor


def _word(text, x0, x1, bottom):
    return {"text": text, "x0": float(x0), "x1": float(x1), "top": float(bottom - 10), "bottom": float(bottom)}


def _rows(words):
    return pdf_extractor._group_words_into_rows(words)


def _two_column_page():
    """Left band 50-250, right band 330-520, gutter ~290. Mirrors a real
    resume: the columns have different lengths, so most rows carry content on
    only one side."""
    words = []
    y = 100
    for i in range(6):  # left-only rows
        words += [_word(f"left{i}", 50, 250, y)]
        y += 20
    for i in range(6):  # right-only rows
        words += [_word(f"right{i}", 330, 520, y)]
        y += 20
    for i in range(4):  # rows with both columns occupied
        words += [_word(f"l{i}", 50, 250, y), _word(f"r{i}", 330, 520, y)]
        y += 20
    return words


def _single_column_page_with_right_aligned_dates():
    """Full-width body prose, plus role rows whose date is right-aligned --
    the layout that must NOT be treated as two columns."""
    words = []
    y = 100
    for i in range(12):
        words += [_word(f"body{i}", 50, 520, y)]
        y += 20
    for i in range(3):
        words += [_word(f"Title{i}", 50, 200, y), _word(f"May 202{i}", 430, 520, y)]
        y += 20
    return words


def test_two_column_page_gutter_is_detected():
    assert pdf_extractor._detect_column_gutter(_rows(_two_column_page())) is not None


def test_single_column_with_right_aligned_dates_is_not_split():
    """The critical false positive: splitting here would separate a role's
    title from its date and destroy role-boundary detection."""
    assert pdf_extractor._detect_column_gutter(_rows(_single_column_page_with_right_aligned_dates())) is None


def test_short_or_sparse_pages_are_never_split():
    assert pdf_extractor._detect_column_gutter(_rows([_word("only", 50, 250, 100)])) is None
    assert pdf_extractor._detect_column_gutter([]) is None


def test_full_width_row_is_kept_whole():
    """A wrapped sentence running across the gutter is one line, not two --
    cutting it would scramble the prose and hand the section mapper two
    fragments, neither reading as what it is."""
    row = [_word("a", 50, 180, 100), _word("b", 185, 300, 100), _word("c", 305, 520, 100)]
    parts = pdf_extractor._split_row_at_gutter(row, 290.0)
    assert len(parts) == 1
    assert parts[0][0] == 0
    assert len(parts[0][1]) == 3


def test_genuine_two_column_row_is_split_into_bands():
    row = [_word("EDUCATION", 50, 160, 100), _word("SKILLS", 330, 420, 100)]
    parts = pdf_extractor._split_row_at_gutter(row, 290.0)
    assert [band for band, _ in parts] == [0, 1]
    assert [w["text"] for _, ws in parts for w in ws] == ["EDUCATION", "SKILLS"]


def test_row_with_a_word_straddling_the_gutter_is_not_split():
    row = [_word("wide", 200, 400, 100)]
    parts = pdf_extractor._split_row_at_gutter(row, 290.0)
    assert len(parts) == 1
