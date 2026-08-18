"""
Dynamic section mapping (spec §6/§8). Deterministic heading-synonym regex
first (extends the proven C# ResumeSectionDetector heuristics -- see the two
regression-tested design choices called out inline below), escalating to
Qwen only for genuinely ambiguous unrecognized headings. UNKNOWN/OTHER is
used rather than forcing ambiguous text into a section.
"""
import re
from dataclasses import dataclass

from app.db.models.common import CanonicalSection
from app.models.resume import Block, SectionAssignment

# Includes the Wingdings/Symbol-font private-use-area codepoints (U+F0A7,
# U+F0B7, U+F076, U+F0D8, ...) that Word-generated PDFs commonly emit for
# bullet glyphs -- these decode as those PUA characters, not a real "•".
_BULLET_START = re.compile(r"^[•\-*o●▪-]\s+")

_PATTERNS: list[tuple[CanonicalSection, re.Pattern]] = [
    (CanonicalSection.EXPERIENCE, re.compile(
        r"\b(EXPERIENCE|EMPLOYMENT HISTORY|CAREER HISTORY|WORK HISTORY|"
        r"PROFESSIONAL EXPERIENCE|PROFESSIONAL HISTORY|WORK EXPERIENCE)\b"
    )),
    (CanonicalSection.SUMMARY, re.compile(
        r"\b(SUMMARY|PROFILE|ABOUT ME|OBJECTIVE|CAREER PROFILE|EXECUTIVE SUMMARY)\b"
    )),
    # SKILLS?/COMPETENCIES/TECHNOLOGIES/TOOLS/EXPERTISE -- TOOLS/TECHNOLOGIES
    # require the plural form deliberately: singular "Tool"/"Technology" are
    # common inside project-title content lines ("Internal Platform Tool")
    # and broadening to singular caused a real bug where a project's own
    # title hijacked the section boundary.
    (CanonicalSection.SKILLS, re.compile(
        r"\bSKILLS?\b|\bCOMPETENCIES\b|\bTECHNOLOGIES\b|\bTOOLS\b|\bEXPERTISE\b|\bTECHNOLOGY STACK\b"
    )),
    # Plural-only for the same reason -- "Project" singular is a common
    # standalone project-title word ("Major Project", "Capstone Project").
    (CanonicalSection.PROJECTS, re.compile(r"\bPROJECTS\b|\bKEY PROJECTS\b|\bSELECTED PROJECTS\b")),
    # Prefix match (no trailing \b) so the adjective form "Educational
    # Qualification(s)" matches too -- the confirmed root cause of a real bug
    # where institution/date content leaked into the preceding section when
    # only the bare noun form was recognized.
    (CanonicalSection.EDUCATION, re.compile(
        r"\bEDUCATION|\bACADEMIC BACKGROUND\b|\bACADEMIC QUALIFICATIONS\b|\bQUALIFICATIONS?\b"
    )),
    (CanonicalSection.CERTIFICATIONS, re.compile(
        r"\b(CERTIFICATIONS|LICENSES|CERTIFICATES|ACCREDITATIONS|CREDENTIALS|"
        r"PROFESSIONAL CERTIFICATIONS)\b"
    )),
    (CanonicalSection.AWARDS, re.compile(r"\bAWARDS\b")),
    (CanonicalSection.ACHIEVEMENTS, re.compile(r"\b(ACHIEVEMENTS|HONORS|ACCOMPLISHMENTS)\b")),
    (CanonicalSection.PUBLICATIONS, re.compile(r"\bPUBLICATIONS\b")),
    (CanonicalSection.INTERESTS, re.compile(r"\b(INTERESTS|HOBBIES)\b")),
    (CanonicalSection.CONTACT, re.compile(
        r"\bCONTACT\b|\bPERSONAL (?:DETAILS|INFORMATION)\b|\bCONTACT INFO(?:RMATION)?\b"
    )),
]

_HEADING_LEN_MAX = 60
_HEADING_WORD_MAX = 5
_AMBIGUOUS_HEADING_LEN_MAX = 40
_AMBIGUOUS_WORD_COUNT_MAX = 5
_HAS_DIGIT = re.compile(r"\d")


def is_possible_heading_line(line: str) -> bool:
    trimmed = line.strip()
    if not trimmed or len(trimmed) > _HEADING_LEN_MAX:
        return False
    if _BULLET_START.match(trimmed):
        return False
    # A heading names a section; it is not a sentence. Responsibility bullets
    # wrap onto unbulleted continuation lines that are short enough to pass
    # the length test above -- "3+ active projects in an agile environment."
    # matched the PROJECTS pattern mid-way through an Experience section and
    # dumped the remaining roles into Projects, losing them entirely.
    if trimmed.endswith((".", ",", ";")):
        return False
    words = trimmed.split()
    if len(words) > _HEADING_WORD_MAX:
        return False
    # A multi-word line starting lower-case is mid-sentence continuation.
    # One- and two-word lower-case lines are left alone, because minimalist
    # templates do legitimately write "education" / "work experience".
    if len(words) >= 3 and trimmed[0].islower():
        return False
    return True


def match_canonical_section(line: str) -> CanonicalSection | None:
    upper = line.strip().upper()
    for section, pattern in _PATTERNS:
        if pattern.search(upper):
            return section
    return None


def looks_like_unrecognized_heading(line: str) -> bool:
    """True for a short, unmatched, header-shaped line worth escalating to
    Qwen as an ambiguous heading candidate (spec §8) -- not for ordinary
    short content lines (locations, GPA lines, date ranges)."""
    trimmed = line.strip()
    if not trimmed or len(trimmed) > _AMBIGUOUS_HEADING_LEN_MAX:
        return False
    if "@" in trimmed or _HAS_DIGIT.search(trimmed):
        return False
    if trimmed.endswith((".", ",", ";", ":")):
        return False
    words = trimmed.split()
    if len(words) > _AMBIGUOUS_WORD_COUNT_MAX:
        return False
    is_capitalized = trimmed == trimmed.upper() or trimmed.istitle()
    return is_capitalized


@dataclass
class SectionMappingResult:
    sections: list[SectionAssignment]
    ambiguous_heading_block_ids: list[str]


def _recurring_line_texts(blocks: list[Block]) -> set[str]:
    """Normalized line texts that occur more than once in the document.

    A section heading names a section, so it appears once; a string that
    recurs is a per-entry template label. This distinction is what stops
    "Achievements/Tasks" -- emitted once per role by several resume builders
    -- from matching the ACHIEVEMENTS pattern and resetting the active
    section mid-way through the Experience section, which shredded one real
    resume's employment history into three bogus ACHIEVEMENTS sections and
    left it scoring 0/25 on Experience. Structural, so it generalizes to any
    recurring label rather than denylisting this one phrase."""
    counts: dict[str, int] = {}
    for b in blocks:
        key = b.text.strip().upper()
        if key:
            counts[key] = counts.get(key, 0) + 1
    return {text for text, n in counts.items() if n > 1}


def map_blocks_to_sections(blocks: list[Block], default_section: CanonicalSection = CanonicalSection.CONTACT) -> SectionMappingResult:
    """Walks blocks in reading order, flushing a SectionAssignment each time a
    recognized heading is encountered. A page/document starting mid-section
    (no repeated header) inherits the previous block's active section."""
    sections: list[SectionAssignment] = []
    ambiguous_ids: list[str] = []
    recurring = _recurring_line_texts(blocks)

    current_section = default_section
    current_confidence = 0.5  # default section is a guess until a real heading is seen
    buffer_block_ids: list[str] = []
    buffer_text: list[str] = []
    buffer_page: int | None = None
    sequence = 0

    def flush():
        nonlocal buffer_block_ids, buffer_text, buffer_page, sequence
        if not buffer_block_ids:
            return
        sections.append(
            SectionAssignment(
                canonical_section=current_section.value,
                confidence=current_confidence,
                page_number=buffer_page or 1,
                sequence=sequence,
                block_ids=list(buffer_block_ids),
                text="\n".join(buffer_text).strip(),
            )
        )
        sequence += 1
        buffer_block_ids = []
        buffer_text = []

    for block in blocks:
        trimmed = block.text.strip()
        if not trimmed:
            continue

        if is_possible_heading_line(trimmed) and trimmed.upper() not in recurring:
            matched = match_canonical_section(trimmed)
            if matched is not None:
                flush()
                current_section = matched
                current_confidence = 0.95
                buffer_page = block.page_number
                continue
            if looks_like_unrecognized_heading(trimmed):
                ambiguous_ids.append(block.block_id)
                # Falls through to regular content handling below -- an
                # unrecognized heading never resets the active section on its
                # own; only a matched canonical heading does.

        if buffer_page is None:
            buffer_page = block.page_number
        buffer_block_ids.append(block.block_id)
        buffer_text.append(trimmed)

    flush()
    return SectionMappingResult(sections=sections, ambiguous_heading_block_ids=ambiguous_ids)
