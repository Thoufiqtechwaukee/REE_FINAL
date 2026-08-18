"""
ResumeExtractionService (spec §7). pdfplumber-based, word-position clustering
into lines -- adapted from the prior Python port's `resume_parser_service.py`.
Coordinate note preserved from that port: pdfplumber uses a top-left origin
(top/bottom measured downward from the page top), so grouping words by
ascending rounded `bottom` reads top-to-bottom correctly.

Never destroys original text: raw_text is the untouched pdfplumber output,
normalized_text is only whitespace/hyphenation-repaired, and both are kept.
"""
import io
import re
from collections import defaultdict

import pdfplumber

from app.extraction.normalizer import normalize_whitespace
from app.models.resume import Block, BoundingBox, Page, ResumeExtractionDocument

_LINE_SPLIT = re.compile(r"\r\n|\r|\n")

# Column-detection thresholds. Deliberately conservative: a false positive
# (splitting a single-column page) is far more damaging than a false negative,
# because it would break role lines whose date sits right-aligned on the same
# row as the title -- exactly what _chunk_experience anchors on.
_MIN_GUTTER_WIDTH = 12.0          # pt; narrower bands are word spacing, not a gutter
_MAX_GUTTER_CROSSING_RATIO = 0.15  # a gutter must be clear on >=85% of rows
_MIN_LINES_PER_COLUMN = 5          # both sides must carry real content
_MIN_INTRA_ROW_GAP = 12.0          # pt of clear space needed to split one row
_MIN_TEXT_SPAN = 100.0             # pt; narrower pages can't hold two columns


def _union_bbox(a: BoundingBox | None, b: BoundingBox | None) -> BoundingBox | None:
    if a is None:
        return b
    if b is None:
        return a
    return BoundingBox(
        x0=min(a.x0, b.x0), x1=max(a.x1, b.x1), top=min(a.top, b.top), bottom=max(a.bottom, b.bottom)
    )


def _merge_hyphenated_lines(lines_with_bboxes: list[tuple[str, BoundingBox | None]]) -> list[tuple[str, BoundingBox | None]]:
    """Block-level equivalent of normalizer.repair_line_wrap_hyphenation --
    operates on (text, bbox) pairs so a merged block's bounding box is the
    union of its source lines rather than misaligning bboxes against a
    line count that repair changed (a real bug in an earlier version of this
    function: joining lines as plain text first, then re-splitting, shifts
    every subsequent bbox index by however many joins already happened)."""
    merged: list[tuple[str, BoundingBox | None]] = []
    i = 0
    while i < len(lines_with_bboxes):
        text, bbox = lines_with_bboxes[i]
        while (
            text
            and text.endswith("-")
            and not text.endswith("--")
            and i + 1 < len(lines_with_bboxes)
            and lines_with_bboxes[i + 1][0]
            and lines_with_bboxes[i + 1][0][0].islower()
        ):
            i += 1
            next_text, next_bbox = lines_with_bboxes[i]
            text = text + next_text
            bbox = _union_bbox(bbox, next_bbox)
        merged.append((text, bbox))
        i += 1
    return merged


def _group_words_into_rows(words: list[dict]) -> list[tuple[float, list[dict]]]:
    """Clusters words into visual rows by rounded Y position, each row's words
    ordered left to right. This is only a *visual* row -- in a multi-column
    page one row can hold text from two unrelated columns, which is what
    _detect_column_gutter/_split_row_at_gutter below exist to separate."""
    groups: dict[float, list] = defaultdict(list)
    for w in words:
        key = round(w["bottom"] / 4.0) * 4.0
        groups[key].append(w)
    return [(key, sorted(groups[key], key=lambda w: w["x0"])) for key in sorted(groups.keys())]


def _detect_column_gutter(rows: list[tuple[float, list[dict]]]) -> float | None:
    """Finds the x of a genuine column gutter, or None for a single-column
    page.

    The distinction that matters: a real gutter is near-empty across *almost
    every row*, whereas the whitespace before a right-aligned date column
    ("Backend Developer Intern .... May 2024 - Jul 2024") is wide on a few
    rows but run straight through by ordinary body text on most. So this
    measures, per 1pt x offset, how many rows have ink there and only accepts
    a band that stays below _MAX_GUTTER_CROSSING_RATIO of all rows -- a plain
    union of word extents would be defeated by a single full-width line.
    """
    all_words = [w for _, row in rows for w in row]
    if len(rows) < 2 * _MIN_LINES_PER_COLUMN or not all_words:
        return None

    min_x = min(w["x0"] for w in all_words)
    max_x = max(w["x1"] for w in all_words)
    span = int(max_x - min_x)
    if span < _MIN_TEXT_SPAN:
        return None

    counts = [0] * (span + 1)
    for _, row in rows:
        touched = bytearray(span + 1)
        for w in row:
            a = max(0, int(w["x0"] - min_x))
            b = min(span, int(w["x1"] - min_x))
            for i in range(a, b + 1):
                touched[i] = 1
        for i, t in enumerate(touched):
            if t:
                counts[i] += 1

    limit = _MAX_GUTTER_CROSSING_RATIO * len(rows)
    best_width = 0
    best_center: float | None = None
    i = 0
    while i <= span:
        if counts[i] > limit:
            i += 1
            continue
        j = i
        while j <= span and counts[j] <= limit:
            j += 1
        # i > 0 and j <= span keeps this to *interior* bands -- the empty
        # margins either side of the text block are not gutters.
        if i > 0 and j <= span and (j - i) > best_width:
            best_width = j - i
            best_center = min_x + (i + j) / 2.0
        i = j

    if best_center is None or best_width < _MIN_GUTTER_WIDTH:
        return None

    # Both sides must carry real content, or this is a stray indent rather
    # than a column boundary.
    left = sum(1 for _, row in rows if max(w["x1"] for w in row) <= best_center)
    right = sum(1 for _, row in rows if min(w["x0"] for w in row) >= best_center)
    if left < _MIN_LINES_PER_COLUMN or right < _MIN_LINES_PER_COLUMN:
        return None
    return best_center


def _split_row_at_gutter(row_words: list[dict], gutter: float) -> list[tuple[int, list[dict]]]:
    """Splits one visual row into per-column pieces, returning (band, words)
    with band 0 = left, 1 = right.

    A row whose words run *continuously* across the gutter is a full-width
    line (a heading, or a wrapped sentence of body prose) and is kept whole --
    cutting one in half would scramble the sentence and, worse, hand the
    section mapper two fragments neither of which reads as what it is. Only a
    row with a real horizontal gap straddling the gutter is a true
    two-column row."""
    straddling = [w for w in row_words if w["x0"] < gutter < w["x1"]]
    if straddling:
        return [(0, row_words)]

    left = [w for w in row_words if w["x1"] <= gutter]
    right = [w for w in row_words if w["x0"] >= gutter]
    if not left or not right:
        return [(0 if left else 1, row_words)]

    gap = min(w["x0"] for w in right) - max(w["x1"] for w in left)
    if gap < _MIN_INTRA_ROW_GAP:
        return [(0, row_words)]
    return [(0, left), (1, right)]


def _extract_lines_with_bboxes(page: "pdfplumber.page.Page") -> list[tuple[str, BoundingBox]]:
    """Groups words into lines and returns each line's text plus a bounding
    box spanning its words, in reading order. Falls back to plain
    page.extract_text() (no bounding boxes) if word extraction fails.

    Multi-column pages are separated into columns first and emitted one
    column at a time (left band fully, then right), because grouping by Y
    alone splices unrelated columns into one line -- the confirmed cause of a
    real bug where a two-column resume produced "EDUCATION SKILLS" as a
    single line, so the EDUCATION heading was swallowed by the SKILLS pattern
    and the whole Education section ceased to exist downstream. Single-column
    pages take the same path as before with band 0 for every row."""
    try:
        words = page.extract_words()
    except Exception:
        words = None

    if not words:
        text = page.extract_text() or ""
        return [(line, None) for line in _LINE_SPLIT.split(text) if line.strip()]

    rows = _group_words_into_rows(words)
    gutter = _detect_column_gutter(rows)

    ordered: list[tuple[int, float, list[dict]]] = []
    if gutter is None:
        ordered = [(0, y, row) for y, row in rows]
    else:
        for y, row in rows:
            for band, part in _split_row_at_gutter(row, gutter):
                ordered.append((band, y, part))
    # Column-major: the whole left column top-to-bottom, then the right.
    # Full-width rows keep band 0, so a header or summary above the columns
    # still leads the document rather than being stranded mid-flow.
    ordered.sort(key=lambda t: (t[0], t[1]))

    lines: list[tuple[str, BoundingBox]] = []
    for _, _, line_words in ordered:
        text = " ".join(w["text"].strip() for w in line_words if w["text"].strip())
        if not text:
            continue
        bbox = BoundingBox(
            x0=min(w["x0"] for w in line_words),
            x1=max(w["x1"] for w in line_words),
            top=min(w["top"] for w in line_words),
            bottom=max(w["bottom"] for w in line_words),
        )
        lines.append((text, bbox))
    return lines


def extract(resume_id: str, pdf_bytes: bytes) -> ResumeExtractionDocument:
    doc = ResumeExtractionDocument(resume_id=resume_id)
    if not pdf_bytes:
        return doc

    sequence = 0
    raw_parts: list[str] = []
    normalized_parts: list[str] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            lines_with_bboxes = _extract_lines_with_bboxes(page)
            raw_page_text = "\n".join(line for line, _ in lines_with_bboxes)

            # Hyphenation repair merges adjacent (text, bbox) pairs directly,
            # so bounding boxes stay correctly attached to the merged text
            # rather than being looked up by an index the merge has shifted.
            repaired_lines = _merge_hyphenated_lines(lines_with_bboxes)
            normalized_lines = [(normalize_whitespace(t), b) for t, b in repaired_lines if t.strip()]
            normalized_page_text = "\n".join(t for t, _ in normalized_lines)

            doc.pages.append(
                Page(page_number=page_index, raw_text=raw_page_text, normalized_text=normalized_page_text)
            )
            raw_parts.append(f"--- PAGE {page_index} ---\n{raw_page_text}")
            normalized_parts.append(normalized_page_text)

            for line_text, bbox in normalized_lines:
                block_id = f"{resume_id}:p{page_index}:b{sequence}"
                doc.blocks.append(
                    Block(
                        block_id=block_id,
                        page_number=page_index,
                        block_type="line",
                        text=line_text,
                        sequence=sequence,
                        bounding_box=bbox,
                    )
                )
                doc.reading_order.append(block_id)
                sequence += 1

    doc.raw_text = "\n".join(raw_parts)
    doc.normalized_text = "\n\n".join(normalized_parts)
    return doc


def get_page_count(pdf_bytes: bytes) -> int:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return len(pdf.pages)
