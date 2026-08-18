"""
SkillDiscoveryService (spec §18/§21). Pipeline: Skills-section candidate
extraction + whole-resume prose scanning -> catalog matching
(taxonomy/skill_matcher) -> Qwen validation only for ambiguous candidates
(agents/skill_validation) -> consolidated, deduplicated discovered-skill list.
This produces AUTO_CONFIRMED candidates for the verification gate (spec
§22/§23) -- nothing here is a final verified skill yet.
"""
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agents.skill_validation import AmbiguousSkillItem, validate_ambiguous_skills
from app.db.models.evaluation import DetectionMethod
from app.db.models.resume import ChunkType, ResumeChunk
from app.db.models.skill import TechnicalSkill
from app.taxonomy import skill_matcher
from app.taxonomy.candidate_filter import is_plausible_skill_candidate

_DELIM_SPLIT = re.compile(r"[\r\n,•▪●-|\t;]+")
_SHORT_SLASH_JOIN = re.compile(r"\b(\w{1,4})\s*/\s*(\w{1,4})\b")

# Bounds on what counts as a "Category:" prefix rather than part of a skill.
_MAX_LABEL_WORDS = 4
_MAX_LABEL_CHARS = 34

_PROSE_CHUNK_TYPES = {
    ChunkType.SUMMARY.value,
    ChunkType.EXPERIENCE_RESPONSIBILITY.value,
    ChunkType.EXPERIENCE_TECHNOLOGY.value,
    ChunkType.EXPERIENCE_PROJECT.value,
    ChunkType.PROJECT.value,
}

# Catalog skill names that double as ordinary English words -- confirmed via
# a real false positive during testing: "Segment" (Twilio Segment, a CDP
# tool) matched the word "segment" in an SAP/EDI resume, where "segment" is
# unrelated SAP terminology for an IDoc data structure component. The prior
# C# system hit the same problem and deliberately excluded Go/Swift/Rust/R
# from its prose-scan phrase list for the identical reason (they are fine as
# literal Skills-section entries -- Layer 1 below -- where intent is
# explicit; only whole-resume prose scanning is precision-risky). This list
# is a pragmatic, non-exhaustive denylist for the clearest cases, not a
# claim of completeness.
_PROSE_SCAN_DENYLIST = {
    n.lower() for n in [
        "Go", "R", "Swift", "Rust", "Segment", "Echo", "Prophet", "Ray",
        "Crystal", "Gin", "Sentry", "Vapor", "Presto", "Bun", "Storybook",
        "Sinatra", "Word2Vec",
    ]
}


def _strip_category_label(segment: str) -> str:
    """Drops a leading "Category:" prefix, keeping only the value side.

    Skills sections are overwhelmingly written as "Backend: FastAPI, REST API
    Design" -- the part before the colon names a *category*, not a skill. The
    previous implementation split on commas but not colons and then stripped
    ':' as punctuation, which turned the label "Backend:" into the candidate
    "Backend" and destroyed the one signal marking it as a label. Because
    "Backend" matches no catalog entry, it fell through to semantic search and
    then to Qwen, which resolved it to ASP.NET Core at 80% confidence on a
    resume containing no .NET whatsoever; "Core CS:" likewise became C++.
    Dropping the label side kills that class of fabrication at the source
    rather than relying on Qwen to decline it."""
    head, sep, tail = segment.partition(":")
    if not sep:
        return segment
    # Only treat it as a label when the head is short and word-like; a colon
    # inside a real skill name ("C++: Advanced") is not a category prefix, and
    # a long head is prose that happens to contain a colon.
    if len(head.split()) <= _MAX_LABEL_WORDS and len(head) <= _MAX_LABEL_CHARS:
        return tail
    return segment


def _extract_skills_section_candidates(text: str) -> list[str]:
    protected = _SHORT_SLASH_JOIN.sub(lambda m: f"{m.group(1)}/{m.group(2)}", text)
    candidates = []
    for raw in _DELIM_SPLIT.split(protected):
        # Label-stripping happens per delimited segment and *before* the
        # punctuation strip, so the trailing colon is still present to be
        # recognized. A segment that is nothing but a label ("Backend:")
        # reduces to empty here and is dropped by the length check below.
        p = _strip_category_label(raw).strip(" .;:()-•")
        if p and 2 <= len(p) <= 60:
            candidates.append(p)
    return candidates


def _build_prose_regex(names_by_lower: dict[str, TechnicalSkill]) -> re.Pattern:
    escaped = sorted((re.escape(name) for name in names_by_lower), key=len, reverse=True)
    pattern = r"(?<![A-Za-z0-9])(?:" + "|".join(escaped) + r")(?![A-Za-z0-9])"
    return re.compile(pattern, re.IGNORECASE)


@dataclass
class DiscoveredSkill:
    skill_id: str
    canonical_name: str
    detected_text: str
    confidence: float
    detection_method: str
    source_chunk_ids: set[str] = field(default_factory=set)


async def discover_skills(db: Session, chunks: list[ResumeChunk]) -> list[DiscoveredSkill]:
    exact_map, alias_map, fuzzy_universe = skill_matcher._catalog_lookup_maps(db)

    all_skills = db.query(TechnicalSkill).filter(TechnicalSkill.active == True).all()
    names_by_lower = {s.canonical_name.lower(): s for s in all_skills}
    prose_regex = _build_prose_regex(names_by_lower) if names_by_lower else None

    found: dict[str, DiscoveredSkill] = {}
    ambiguous_items: list[AmbiguousSkillItem] = []
    ambiguous_source: dict[str, str] = {}  # detected_text -> chunk_id (first seen)

    def _accept(skill: TechnicalSkill, detected_text: str, confidence: float, method: str, chunk_id: str):
        existing = found.get(skill.skill_id)
        if existing is None:
            found[skill.skill_id] = DiscoveredSkill(
                skill_id=skill.skill_id,
                canonical_name=skill.canonical_name,
                detected_text=detected_text,
                confidence=confidence,
                detection_method=method,
                source_chunk_ids={chunk_id} if chunk_id else set(),
            )
        else:
            if chunk_id:
                existing.source_chunk_ids.add(chunk_id)
            if confidence > existing.confidence:
                existing.confidence = confidence
                existing.detection_method = method

    # --- Layer 1: Skills-section structural candidates ---
    # Every (chunk, candidate_text) occurrence is collected first -- including
    # duplicates across multiple Skills sections (spec §70 edge case: multiple
    # Skills sections) -- so per-occurrence source-chunk tracking below is
    # unchanged from before; only the matching call itself is batched: one
    # embedding round-trip for every *unique* candidate text that needs
    # semantic fallback, instead of one round-trip per occurrence.
    skill_section_chunks = [c for c in chunks if c.chunk_type == ChunkType.SKILL_SECTION.value or c.chunk_type == ChunkType.SKILL_SECTION]
    chunk_candidate_pairs: list[tuple[ResumeChunk, str]] = [
        (chunk, candidate_text)
        for chunk in skill_section_chunks
        for candidate_text in _extract_skills_section_candidates(chunk.original_text)
    ]
    unique_candidate_texts = list({text for _, text in chunk_candidate_pairs})
    candidates_by_text = await skill_matcher.find_candidates_batch(db, unique_candidate_texts, exact_map, alias_map, fuzzy_universe)

    for chunk, candidate_text in chunk_candidate_pairs:
        candidates = candidates_by_text.get(candidate_text, [])
        if not candidates:
            continue
        if skill_matcher.is_confident(candidates):
            top = candidates[0]
            _accept(top.skill, candidate_text, top.confidence, top.method, chunk.chunk_id)
        else:
            ambiguous_items.append(AmbiguousSkillItem(detected_text=candidate_text, candidates=candidates[:5]))
            ambiguous_source.setdefault(candidate_text, chunk.chunk_id)

    # --- Layer 2: catalog-name scanning ---
    # Runs over prose chunks *and* the Skills section. Layer 1 splits the
    # Skills section on delimiters, which misses chip/tag layouts that
    # separate entries with spaces alone ("Python SQL Machine Learning
    # Vue.js" renders as four chips but is one delimiter-free line) -- a real
    # resume lost its entire skill list that way once its sections were
    # mapped correctly, because Layer 1 produced one unmatchable blob per
    # line. The denylist is applied only outside the Skills section: "Go" or
    # "R" appearing in prose is ambiguous, but listed as a skill it is an
    # explicit claim, which is the distinction the denylist was written for.
    if prose_regex is not None:
        for chunk in chunks:
            chunk_type_val = chunk.chunk_type.value if hasattr(chunk.chunk_type, "value") else chunk.chunk_type
            is_skills_section = chunk_type_val == ChunkType.SKILL_SECTION.value
            if chunk_type_val not in _PROSE_CHUNK_TYPES and not is_skills_section:
                continue
            for match in prose_regex.finditer(chunk.original_text or ""):
                matched_text = match.group(0)
                if not is_skills_section and matched_text.lower() in _PROSE_SCAN_DENYLIST:
                    continue
                skill = names_by_lower.get(matched_text.lower())
                if skill is None:
                    continue
                if skill.skill_id in found:
                    found[skill.skill_id].source_chunk_ids.add(chunk.chunk_id)
                    continue
                _accept(skill, matched_text, 0.85, DetectionMethod.EXACT.value, chunk.chunk_id)

    # --- Layer 3: Qwen validation for ambiguous Skills-section candidates ---
    if ambiguous_items:
        verdicts = await validate_ambiguous_skills(ambiguous_items)
        for item in ambiguous_items:
            verdict = verdicts.get(item.detected_text)
            chunk_id = ambiguous_source.get(item.detected_text, "")
            if verdict is None:
                # No verdict obtainable -- keep the deterministic top candidate
                # rather than silently dropping a real skill claim.
                top = item.candidates[0]
                _accept(top.skill, item.detected_text, top.confidence * 0.8, top.method, chunk_id)
                continue
            if verdict.chosen_skill_id is None:
                continue  # Qwen explicitly judged this not a real skill claim.
            chosen = next((c.skill for c in item.candidates if c.skill.skill_id == verdict.chosen_skill_id), None)
            if chosen is not None:
                _accept(chosen, item.detected_text, verdict.confidence, DetectionMethod.QWEN_VALIDATED.value, chunk_id)

    # Defense in depth: a skill whose surviving detected_text fails the
    # generic-noun filter must still be dropped unless Qwen explicitly
    # confirmed it -- catches the case where a low-quality raw match term
    # slipped through prose/fuzzy matching.
    return [
        d
        for d in found.values()
        if is_plausible_skill_candidate(d.detected_text) or d.detection_method == DetectionMethod.QWEN_VALIDATED.value
    ]
