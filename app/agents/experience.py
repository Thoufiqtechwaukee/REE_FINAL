"""
Experience analysis (spec §30-33). Deterministic date/duration/overlap/gap
math (never LLM), entry validation per §31, role normalization via
taxonomy/role_matcher. Only genuinely ambiguous entries (structurally
plausible but unclear whether they're real employment) go to Qwen, batched.
"""
import logging
import re
from datetime import date

from sqlalchemy.orm import Session

from app.agents.responsibility_classifier import classify_role
from app.core.config import get_settings
from app.core.dates import DateInterval, calculate_months_between, calculate_total_merged_months
from app.db.models.evaluation import ResumeExperience
from app.db.models.resume import ChunkType, ResumeChunk, ResumeGap
from app.taxonomy import role_matcher

logger = logging.getLogger(__name__)

_MIN_TITLE_LEN = 2
_MAX_TITLE_LEN = 120


def _looks_like_real_role(company: str | None, role_raw: str | None) -> bool:
    """Spec §31 rejection rules: reject records without enough evidence to be
    a real employment entry (no company AND no title at all)."""
    if not company and not role_raw:
        return False
    if role_raw and (len(role_raw) < _MIN_TITLE_LEN or len(role_raw) > _MAX_TITLE_LEN):
        return False
    return True


async def build_experience_records(db: Session, resume_id: str) -> list[ResumeExperience]:
    role_chunks = (
        db.query(ResumeChunk)
        .filter(ResumeChunk.resume_id == resume_id, ResumeChunk.chunk_type == ChunkType.EXPERIENCE_ROLE.value)
        .order_by(ResumeChunk.sequence)
        .all()
    )
    all_experience_chunks = (
        db.query(ResumeChunk)
        .filter(
            ResumeChunk.resume_id == resume_id,
            ResumeChunk.chunk_type.in_([ChunkType.EXPERIENCE_RESPONSIBILITY.value, ChunkType.EXPERIENCE_TECHNOLOGY.value]),
        )
        .all()
    )
    children_by_parent: dict[str, list[ResumeChunk]] = {}
    for c in all_experience_chunks:
        if c.parent_chunk_id:
            children_by_parent.setdefault(c.parent_chunk_id, []).append(c)

    level_by_name = role_matcher.load_level_by_name(db)

    # Sort chronologically (earliest first) so the ambiguous-title Qwen
    # fallback can inherit the *previous* (earlier) role's level.
    def sort_key(chunk: ResumeChunk):
        return chunk.start_date or date.min

    sorted_role_chunks = sorted(role_chunks, key=sort_key)

    # Role-catalog matching is hoisted out of the loop below: the catalog is
    # loaded once and every title needing semantic fallback is embedded in one
    # request, instead of two SQL queries + a possible embedding round-trip
    # per role. Only titles that survive _looks_like_real_role are matched --
    # exactly the set the loop would have queried, so no wasted work. The loop
    # itself stays sequential: classify_seniority threads previous_level_id
    # from the chronologically-earlier role, which is a real data dependency.
    matchable_titles = [
        c.role_raw for c in sorted_role_chunks
        if c.role_raw and _looks_like_real_role(c.company, c.role_raw)
    ]
    candidates_by_title = (
        await role_matcher.find_candidates_batch(db, matchable_titles) if matchable_titles else {}
    )

    db.query(ResumeExperience).filter(ResumeExperience.resume_id == resume_id).delete()

    records: list[ResumeExperience] = []
    previous_level_id: int | None = None
    for seq_idx, chunk in enumerate(sorted_role_chunks):
        if not _looks_like_real_role(chunk.company, chunk.role_raw):
            continue

        children = children_by_parent.get(chunk.chunk_id, [])
        responsibilities = [c.original_text for c in children if c.chunk_type == ChunkType.EXPERIENCE_RESPONSIBILITY.value]
        technologies_raw = [c.original_text for c in children if c.chunk_type == ChunkType.EXPERIENCE_TECHNOLOGY.value]
        technologies = [t for line in technologies_raw for t in _split_tech_line(line)]

        role_level_label, leadership_indicators, ownership_indicators = classify_role(responsibilities)

        duration_months = 0
        if chunk.start_date and chunk.end_date:
            duration_months = calculate_months_between(chunk.start_date, chunk.end_date)

        canonical_role_id = None
        canonical_title = None
        role_family = None
        seniority_level_id = None
        seniority_ambiguous = False
        if chunk.role_raw:
            candidates = candidates_by_title.get(chunk.role_raw, [])
            if candidates and role_matcher.is_confident(candidates):
                top = candidates[0].role
                canonical_role_id = top.role_id
                canonical_title = top.canonical_title
                role_family = top.role_family
                seniority_level_id = top.seniority_level_id

            seniority = role_matcher.classify_seniority(chunk.role_raw, level_by_name, previous_level_id)
            if seniority_level_id is None:
                seniority_level_id = seniority.level_id
            seniority_ambiguous = seniority.is_ambiguous
            if seniority.level_id is not None:
                previous_level_id = seniority.level_id

        record = ResumeExperience(
            resume_id=resume_id,
            company=chunk.company or "Unknown",
            raw_title=chunk.role_raw or "Unknown",
            canonical_role_id=canonical_role_id,
            canonical_title=canonical_title,
            role_family=role_family,
            seniority_level_id=seniority_level_id,
            seniority_ambiguous=seniority_ambiguous,
            start_date=chunk.start_date,
            end_date=chunk.end_date,
            is_current=chunk.is_current,
            duration_months=duration_months,
            responsibilities=responsibilities,
            technologies=technologies,
            projects=[],
            leadership_indicators=leadership_indicators,
            ownership_indicators=ownership_indicators,
            responsibility_level=role_level_label,
            source_chunk_ids=[chunk.chunk_id] + [c.chunk_id for c in children],
            confidence=1.0 if (chunk.start_date and chunk.end_date) else 0.5,
            sequence=seq_idx,
        )
        db.add(record)
        records.append(record)

    db.commit()
    return records


def _split_tech_line(line: str) -> list[str]:
    parts = re.split(r"[,;/]|\band\b", line)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def compute_total_experience_months(records: list[ResumeExperience]) -> int:
    intervals = [DateInterval(r.start_date, r.end_date) for r in records if r.start_date and r.end_date]
    return calculate_total_merged_months(intervals)


def detect_gaps(db: Session, resume_id: str, records: list[ResumeExperience]) -> list[ResumeGap]:
    settings = get_settings()
    threshold_months = settings.gap_threshold_months

    dated = sorted(
        [r for r in records if r.start_date and r.end_date],
        key=lambda r: r.start_date,
    )
    db.query(ResumeGap).filter(ResumeGap.resume_id == resume_id).delete()

    gaps: list[ResumeGap] = []
    for prev, nxt in zip(dated, dated[1:]):
        if nxt.start_date <= prev.end_date:
            continue  # overlapping, not a gap
        gap_months = calculate_months_between(prev.end_date, nxt.start_date) - 1
        if gap_months >= threshold_months:
            gap = ResumeGap(
                resume_id=resume_id,
                gap_start=prev.end_date,
                gap_end=nxt.start_date,
                duration_months=gap_months,
                explanation=None,  # never invented -- spec §33: only call a gap explained if documentation exists
                confidence=None,
            )
            db.add(gap)
            gaps.append(gap)

    db.commit()
    return gaps
