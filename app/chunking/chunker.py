"""
ResumeChunkingService (spec §9/§10). Chunks by resume meaning, not fixed
token windows: EXPERIENCE splits into one role header + one chunk per
responsibility bullet + an optional technology-environment chunk (the
bullet-level granularity is a proven pattern from the prior system's own
BuildResumeChunks -- evidence/growth reasoning needs per-bullet resolution,
not per-role blobs). PROJECTS/EDUCATION/CERTIFICATIONS/ACHIEVEMENTS/
PUBLICATIONS use a title+description list splitter. Fallback order per §10:
logical section boundaries first, then paragraph/bullet/list splitting;
token-window fallback is not needed at the scale of a single resume (a
section that produces zero recognizable boundaries just becomes one chunk).
"""
import re
from datetime import date

from app.core.dates import parse_date_range
from app.db.models.common import CanonicalSection
from app.models.chunk import ChunkDraft
from app.models.resume import Block, ResumeExtractionDocument
from app.extraction.section_mapper import SectionMappingResult
from app.taxonomy.candidate_filter import is_location_text

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
_YEAR = r"(?:\d{4}|\d{2})"
_APOS = r"[’']?"
_MONTH_YEAR = rf"{_MONTH}\s*{_APOS}\s*{_YEAR}"
_SLASH_DATE = r"\d{1,2}[/.]\d{4}"
_BARE_YEAR = r"\b(?:19|20)\d{2}\b"
_DATE_TOKEN = rf"(?:{_MONTH_YEAR}|{_SLASH_DATE}|{_BARE_YEAR})"
_OPEN_END = r"(?:Present|Current|Till\s*[Dd]ate|Now|Ongoing)"

_DATE_RANGE_LINE = re.compile(
    rf"(?P<range>{_DATE_TOKEN}\s*(?:–|—|-|\bto\b)\s*(?:{_DATE_TOKEN}|{_OPEN_END}))",
    re.IGNORECASE,
)

_LABEL_COMPANY = re.compile(r"^(?:Client|Company|Employer|Organization)\s*[:\-]\s*(?P<val>.+)$", re.IGNORECASE)
_LABEL_ROLE = re.compile(r"^(?:Role|Title|Position|Designation)\s*[:\-]\s*(?P<val>.+)$", re.IGNORECASE)
_LABEL_ENV = re.compile(
    r"^(?:Environment|Technologies|Tech\s*Stack|Tools\s*(?:&|and)?\s*Technologies|Module)\s*[:\-]\s*(?P<val>.+)$",
    re.IGNORECASE,
)
_LABEL_LOCATION = re.compile(r"^Location\s*[:\-]\s*(?P<val>.+)$", re.IGNORECASE)
_LABEL_SKIP = re.compile(r"^Responsibilities\s*:?\s*$", re.IGNORECASE)

_BULLET_PREFIX = re.compile(r"^[•\-*o●▪-]\s*")


# Supersedes the class above, which is retained verbatim for its Wingdings
# private-use-area bullet codepoints. The fix: the letter 'o' list marker now
# requires following whitespace. Written as "[...o...]\s*" with \s* meaning
# zero-or-more, it matched *any* word beginning with a lower-case o -- so
# "online" registered as a bulleted line, and _strip_bullet rewrote
# "owned delivery" to "wned delivery", silently corrupting responsibility text
# and truncating the header scan that looks for a role's company.
_BULLET_PREFIX = re.compile("^(?:[•\\-*●▪-]\\s*|o\\s+)")


def _strip_bullet(text: str) -> str:
    return _BULLET_PREFIX.sub("", text).strip()


def _looks_like_title(text: str) -> bool:
    trimmed = text.strip()
    if not trimmed or len(trimmed) > 90:
        return False
    if _BULLET_PREFIX.match(trimmed):
        return False
    if trimmed.endswith("."):
        return False
    return True


# Words that mark a line as a job title rather than an employer name. Used to
# decide which of an entry's non-date lines is the role and which is the
# company, since resume templates order the two both ways.
_TITLE_WORDS = re.compile(
    r"\b(intern|engineer|developer|manager|analyst|consultant|architect|designer|"
    r"scientist|administrator|specialist|lead|director|officer|associate|trainee|"
    r"executive|head|programmer|technician|coordinator|supervisor|founder)\b",
    re.IGNORECASE,
)
# Employment-mode noise sitting between the title and the dates in several
# templates -- neither company nor role.
_ENTRY_NOISE = re.compile(
    r"^(online(\s+internship)?|remote|onsite|on-site|hybrid|full[\s-]?time|"
    r"part[\s-]?time|internship|contract|freelance)$",
    re.IGNORECASE,
)


def _clean_entry_line(text: str) -> str:
    """Strips the date range and surrounding separators off a line, leaving
    just company/title text (empty if the line held only a date). The comma
    matters: a date row written "01/2025 - 03/2025," left a bare "," behind,
    and "," is truthy, so it passed validation as a company name."""
    return _DATE_RANGE_LINE.sub("", text).strip(" ,-–—:|·\t")


def _entry_context_lines(blocks: list[Block], start: int, stop: int, step: int, limit: int = 3) -> list[str]:
    """Company/title-bearing lines near an anchor, nearest first.

    Scanning stops at the first bulleted line, because bullets begin the
    responsibilities and therefore end the header block. Without that stop the
    forward scan runs past the current entry's bullets into the *next* entry's
    stacked header and picks up its title -- so a two-role resume recorded
    role 1 as "Senior Developer", role 2's title."""
    out: list[str] = []
    for i in range(start, stop, step):
        text = blocks[i].text.strip()
        if not text:
            continue
        if _BULLET_PREFIX.match(text):
            break
        if _DATE_RANGE_LINE.search(text):
            continue
        cleaned = _clean_entry_line(text)
        if cleaned and not _ENTRY_NOISE.match(cleaned):
            out.append(cleaned)
            if len(out) >= limit:
                break
    return out


def _looks_like_entry_header(text: str) -> bool:
    """True for a line that could be a company or job title, as opposed to
    wrapped bullet prose. Responsibility text wraps onto unbulleted
    continuation lines, so proximity to the date row is not enough on its own
    -- "fraud prevention." and "automate land registration processes,
    ensuring immutability and" both sit directly above a role header."""
    if not text:
        return False
    trimmed = text.strip()
    if not trimmed or len(trimmed) > 90:
        return False
    if trimmed.endswith("."):
        return False
    if trimmed[0].islower():
        return False  # mid-sentence continuation
    if len(trimmed.split()) > 8:
        return False  # reads as prose, not a name or title
    if _ENTRY_NOISE.match(trimmed):
        return False
    return not is_location_text(trimmed)


def _first_title(lines: list[str]) -> str | None:
    return next((c for c in lines if _TITLE_WORDS.search(c)), None)


def _resolve_company_and_role(
    anchor_text: str, before: list[str], after: list[str]
) -> tuple[str | None, str | None]:
    """Picks company and role from an entry's candidate lines.

    Templates disagree on layout: some put the date alone on its own row with
    "Company / Title" stacked above it, others put the title and a right-
    aligned date on one row with the company beneath. Rather than encode
    either layout, this locates the job title by vocabulary and takes the
    company from the *same* side of the date row -- a resume entry's header is
    contiguous, so pulling the company from across the date row is how
    "Achievements/Tasks" (the next entry's label) ends up recorded as an
    employer. Returns None for either field rather than guessing, letting the
    caller's validation reject a truly headerless entry."""
    head = [t for t in [_clean_entry_line(anchor_text)] if _looks_like_entry_header(t)]
    before = [b for b in before if _looks_like_entry_header(b)]
    after = [a for a in after if _looks_like_entry_header(a)]

    # Prefer whichever side actually carries a job title; the anchor row and
    # the lines below it form one group, the lines above it the other.
    anchor_side = head + after
    primary = anchor_side if _first_title(anchor_side) else before

    role = _first_title(primary)
    company = next((c for c in primary if c != role), None)
    if role is None and company is None:
        return None, None
    return company, role


class _BlockIndex:
    def __init__(self, doc: ResumeExtractionDocument):
        self._by_id = {b.block_id: b for b in doc.blocks}

    def resolve(self, block_ids: list[str]) -> list[Block]:
        return [self._by_id[bid] for bid in block_ids if bid in self._by_id]


def chunk_document(doc: ResumeExtractionDocument, section_result: SectionMappingResult) -> list[ChunkDraft]:
    index = _BlockIndex(doc)
    drafts: list[ChunkDraft] = []
    seq = 0

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq - 1

    for section in section_result.sections:
        blocks = index.resolve(section.block_ids)
        if not blocks:
            continue
        canonical = section.canonical_section

        if canonical == CanonicalSection.EXPERIENCE.value:
            drafts.extend(_chunk_experience(blocks, section.canonical_section, next_seq))
        elif canonical in (
            CanonicalSection.PROJECTS.value,
            CanonicalSection.EDUCATION.value,
            CanonicalSection.CERTIFICATIONS.value,
            CanonicalSection.ACHIEVEMENTS.value,
            CanonicalSection.AWARDS.value,
            CanonicalSection.PUBLICATIONS.value,
        ):
            chunk_type = {
                CanonicalSection.PROJECTS.value: "PROJECT",
                CanonicalSection.EDUCATION.value: "EDUCATION",
                CanonicalSection.CERTIFICATIONS.value: "CERTIFICATION",
                CanonicalSection.ACHIEVEMENTS.value: "ACHIEVEMENT",
                CanonicalSection.AWARDS.value: "ACHIEVEMENT",
                CanonicalSection.PUBLICATIONS.value: "PUBLICATION",
            }[canonical]
            drafts.extend(_chunk_list_section(blocks, chunk_type, section.canonical_section, next_seq))
        else:
            chunk_type = {
                CanonicalSection.CONTACT.value: "CONTACT",
                CanonicalSection.SUMMARY.value: "SUMMARY",
                CanonicalSection.SKILLS.value: "SKILL_SECTION",
            }.get(canonical, "OTHER")
            text = "\n".join(b.text for b in blocks).strip()
            if text:
                drafts.append(
                    ChunkDraft(
                        chunk_type=chunk_type,
                        section=canonical,
                        original_text=text,
                        page_number=blocks[0].page_number,
                        sequence=next_seq(),
                        source_block_ids=[b.block_id for b in blocks],
                    )
                )

    return drafts


def _chunk_list_section(blocks: list[Block], chunk_type: str, section: str, next_seq) -> list[ChunkDraft]:
    """Title+description splitter (spec §10 fallback order: paragraph/bullet
    boundaries first). A non-bulleted line <=90 chars not ending in '.'
    starts a new entry; everything else accumulates as that entry's
    description. If no title-looking line is ever seen, the whole section
    becomes one chunk rather than being force-split."""
    drafts: list[ChunkDraft] = []
    current_title: str | None = None
    current_lines: list[str] = []
    current_block_ids: list[str] = []
    current_page: int | None = None
    any_title_seen = False

    def flush():
        if not current_lines and not current_title:
            return
        text = "\n".join(([current_title] if current_title else []) + current_lines).strip()
        if text:
            drafts.append(
                ChunkDraft(
                    chunk_type=chunk_type,
                    section=section,
                    original_text=text,
                    page_number=current_page or (blocks[0].page_number if blocks else 1),
                    sequence=next_seq(),
                    source_block_ids=list(current_block_ids),
                )
            )

    for b in blocks:
        text = b.text.strip()
        if not text:
            continue
        if _looks_like_title(text):
            flush()
            current_title = text
            current_lines = []
            current_block_ids = [b.block_id]
            current_page = b.page_number
            any_title_seen = True
        else:
            if current_page is None:
                current_page = b.page_number
            current_lines.append(_strip_bullet(text))
            current_block_ids.append(b.block_id)

    flush()

    if not any_title_seen and not drafts:
        # No title-shaped line at all -- whole section as one chunk.
        text = "\n".join(_strip_bullet(b.text) for b in blocks).strip()
        if text:
            drafts = [
                ChunkDraft(
                    chunk_type=chunk_type,
                    section=section,
                    original_text=text,
                    page_number=blocks[0].page_number,
                    sequence=next_seq(),
                    source_block_ids=[b.block_id for b in blocks],
                )
            ]
    return drafts


def _chunk_experience(blocks: list[Block], section: str, next_seq) -> list[ChunkDraft]:
    # Real role-boundary lines ("Client: X  June'19 - Till date") are never
    # bullet-prefixed -- excluding bulleted lines from anchor candidacy is
    # what stops a responsibility bullet that happens to mention an unrelated
    # date range ("...research from 2015-2017 in school library") from being
    # misread as a new role starting.
    anchor_indices = [
        i for i, b in enumerate(blocks)
        if _DATE_RANGE_LINE.search(b.text) and not _BULLET_PREFIX.match(b.text.strip())
    ]

    if not anchor_indices:
        # No dated role boundaries found at all -- fall back to one pseudo-role
        # header plus one responsibility chunk per bullet line, so responsibility
        # evidence isn't lost just because dates weren't machine-parseable.
        role_seq = next_seq()
        drafts = [
            ChunkDraft(
                chunk_type="EXPERIENCE_ROLE",
                section=section,
                original_text="(Undated experience entries)",
                page_number=blocks[0].page_number,
                sequence=role_seq,
                source_block_ids=[],
            )
        ]
        for b in blocks:
            text = _strip_bullet(b.text)
            if text:
                drafts.append(
                    ChunkDraft(
                        chunk_type="EXPERIENCE_RESPONSIBILITY",
                        section=section,
                        original_text=text,
                        page_number=b.page_number,
                        sequence=next_seq(),
                        source_block_ids=[b.block_id],
                        parent_sequence=role_seq,
                    )
                )
        return drafts

    drafts: list[ChunkDraft] = []
    boundaries = anchor_indices + [len(blocks)]
    for k, start_idx in enumerate(anchor_indices):
        end_idx = boundaries[k + 1]
        role_blocks = blocks[start_idx:end_idx]
        anchor_block = role_blocks[0]
        anchor_text = anchor_block.text

        date_match = _DATE_RANGE_LINE.search(anchor_text)
        parsed = parse_date_range(date_match.group("range"), today=date.today()) if date_match else None

        company = None
        role_raw = None
        m = _LABEL_COMPANY.match(anchor_text.strip())
        if m:
            company = _DATE_RANGE_LINE.sub("", m.group("val")).strip(" -–—")
        else:
            # Positional resolution: look at the lines immediately before the
            # anchor (bounded by the previous role's anchor so one entry never
            # steals another's header) and immediately after it, then let
            # _resolve_company_and_role decide which is which.
            prev_anchor = anchor_indices[k - 1] if k > 0 else -1
            before = _entry_context_lines(blocks, start_idx - 1, prev_anchor, -1)
            after = _entry_context_lines(blocks, start_idx + 1, min(end_idx, len(blocks)), 1, limit=2)
            company, role_raw = _resolve_company_and_role(anchor_text, before, after)

        responsibilities: list[str] = []
        tech_line: str | None = None
        role_block_ids = [anchor_block.block_id]

        for b in role_blocks[1:]:
            text = b.text.strip()
            if not text:
                continue
            role_block_ids.append(b.block_id)

            if role_raw is None:
                m = _LABEL_ROLE.match(text)
                if m:
                    role_raw = m.group("val").strip()
                    continue
            if _LABEL_LOCATION.match(text) or _LABEL_SKIP.match(text):
                continue
            m = _LABEL_ENV.match(text)
            if m:
                tech_line = m.group("val").strip()
                continue
            responsibilities.append(_strip_bullet(text))

        role_header_text = "\n".join(
            t for t in [anchor_text, f"Role: {role_raw}" if role_raw else None] if t
        )

        role_seq = next_seq()
        drafts.append(
            ChunkDraft(
                chunk_type="EXPERIENCE_ROLE",
                section=section,
                original_text=role_header_text,
                page_number=anchor_block.page_number,
                sequence=role_seq,
                source_block_ids=role_block_ids,
                company=company,
                role_raw=role_raw,
                start_date=parsed.start if parsed else None,
                end_date=parsed.end if parsed else None,
                is_current=parsed.is_current if parsed else False,
            )
        )

        for resp in responsibilities:
            if resp:
                drafts.append(
                    ChunkDraft(
                        chunk_type="EXPERIENCE_RESPONSIBILITY",
                        section=section,
                        original_text=resp,
                        page_number=anchor_block.page_number,
                        sequence=next_seq(),
                        source_block_ids=[],
                        company=company,
                        role_raw=role_raw,
                        start_date=parsed.start if parsed else None,
                        end_date=parsed.end if parsed else None,
                        is_current=parsed.is_current if parsed else False,
                        parent_sequence=role_seq,
                    )
                )

        if tech_line:
            drafts.append(
                ChunkDraft(
                    chunk_type="EXPERIENCE_TECHNOLOGY",
                    section=section,
                    original_text=tech_line,
                    page_number=anchor_block.page_number,
                    sequence=next_seq(),
                    source_block_ids=[],
                    company=company,
                    role_raw=role_raw,
                    start_date=parsed.start if parsed else None,
                    end_date=parsed.end if parsed else None,
                    is_current=parsed.is_current if parsed else False,
                    parent_sequence=role_seq,
                )
            )

    return drafts
