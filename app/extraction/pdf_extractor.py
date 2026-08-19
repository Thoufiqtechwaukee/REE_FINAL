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


def _extract_lines_with_bboxes(page: "pdfplumber.page.Page") -> list[tuple[str, BoundingBox]]:
    """Groups words into lines by rounded Y position, returns each line's
    text plus a bounding box spanning its words. Falls back to plain
    page.extract_text() (no bounding boxes) if word extraction fails."""
    try:
        words = page.extract_words()
    except Exception:
        words = None

    if not words:
        text = page.extract_text() or ""
        return [(line, None) for line in _LINE_SPLIT.split(text) if line.strip()]

    groups: dict[float, list] = defaultdict(list)
    for w in words:
        key = round(w["bottom"] / 4.0) * 4.0
        groups[key].append(w)

    lines: list[tuple[str, BoundingBox]] = []
    for key in sorted(groups.keys()):
        line_words = sorted(groups[key], key=lambda w: w["x0"])
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
