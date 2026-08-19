"""
SkillDiscoveryService matching pipeline (spec §18): exact -> alias -> fuzzy
-> Nomic semantic. A candidate is only ever accepted if it resolves to a real
TechnicalSkill catalog row (spec §16/§46) -- this module never returns
anything else. Ambiguity resolution (deciding whether the top candidate is
confident enough, or Qwen needs to pick between rivals) is the caller's job
(agents/skill_discovery.py) -- this module just ranks candidates.
"""
import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from app.db.models.skill import TechnicalSkill, TechnicalSkillAlias
from app.retrieval.skill_retrieval import search_skill_candidates
from app.taxonomy.candidate_filter import is_plausible_skill_candidate

_LOOSE_KEY_STRIP = re.compile(r"[\s\-.]+")

FUZZY_THRESHOLD = 88
SEMANTIC_THRESHOLD = 0.55
HIGH_CONFIDENCE_THRESHOLD = 0.92


def loose_key(text: str) -> str:
    return _LOOSE_KEY_STRIP.sub("", text or "").lower()


@dataclass
class SkillMatchCandidate:
    skill: TechnicalSkill
    confidence: float
    method: str  # EXACT | ALIAS | FUZZY | SEMANTIC


def _catalog_lookup_maps(db: Session) -> tuple[dict[str, TechnicalSkill], dict[str, TechnicalSkill], dict[str, TechnicalSkill]]:
    """Builds loose-key lookup maps once per call site's batch -- callers
    processing many candidates against the same session should cache this
    rather than rebuilding it per candidate."""
    skills = db.query(TechnicalSkill).filter(TechnicalSkill.active == True).all()
    exact_map: dict[str, TechnicalSkill] = {}
    for s in skills:
        exact_map[loose_key(s.canonical_name)] = s
        exact_map.setdefault(loose_key(s.display_name), s)

    aliases = db.query(TechnicalSkillAlias).join(TechnicalSkill).filter(TechnicalSkill.active == True).all()
    alias_map: dict[str, TechnicalSkill] = {}
    for a in aliases:
        alias_map[loose_key(a.alias_text)] = a.skill

    fuzzy_universe: dict[str, TechnicalSkill] = dict(exact_map)
    for a in aliases:
        fuzzy_universe.setdefault(a.alias_text.lower(), a.skill)

    return exact_map, alias_map, fuzzy_universe


def match_exact_and_alias(text: str, exact_map: dict, alias_map: dict) -> SkillMatchCandidate | None:
    key = loose_key(text)
    if key in exact_map:
        return SkillMatchCandidate(skill=exact_map[key], confidence=1.0, method="EXACT")
    if key in alias_map:
        return SkillMatchCandidate(skill=alias_map[key], confidence=0.97, method="ALIAS")
    return None


def match_fuzzy(text: str, fuzzy_universe: dict[str, TechnicalSkill], threshold: int = FUZZY_THRESHOLD) -> SkillMatchCandidate | None:
    if not fuzzy_universe:
        return None
    match = process.extractOne(text, fuzzy_universe.keys(), scorer=fuzz.WRatio, score_cutoff=threshold)
    if not match:
        return None
    matched_key, score, _ = match
    return SkillMatchCandidate(skill=fuzzy_universe[matched_key], confidence=score / 100.0, method="FUZZY")


async def match_semantic(
    db: Session, text: str, top_k: int = 5, min_similarity: float = SEMANTIC_THRESHOLD
) -> list[SkillMatchCandidate]:
    hits = await search_skill_candidates(db, text, top_k=top_k, min_similarity=min_similarity)
    return [SkillMatchCandidate(skill=skill, confidence=score, method="SEMANTIC") for skill, score in hits]


async def find_candidates(
    db: Session,
    text: str,
    exact_map: dict | None = None,
    alias_map: dict | None = None,
    fuzzy_universe: dict | None = None,
) -> list[SkillMatchCandidate]:
    """Returns ranked candidates, best first. Empty list means "not a
    recognized technical skill" -- callers must not fabricate a skill in that
    case. Pass pre-built exact_map/alias_map/fuzzy_universe (from
    _catalog_lookup_maps) when matching many candidates in one pass to avoid
    rebuilding the catalog lookup per candidate."""
    if not is_plausible_skill_candidate(text):
        return []

    if exact_map is None or alias_map is None or fuzzy_universe is None:
        exact_map, alias_map, fuzzy_universe = _catalog_lookup_maps(db)

    exact_or_alias = match_exact_and_alias(text, exact_map, alias_map)
    if exact_or_alias is not None:
        return [exact_or_alias]

    fuzzy = match_fuzzy(text, fuzzy_universe)
    if fuzzy is not None and fuzzy.confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return [fuzzy]

    semantic = await match_semantic(db, text)

    candidates = [c for c in [fuzzy] if c is not None] + semantic
    # Dedup by skill_id, keeping the highest-confidence method's result.
    best_by_skill: dict[str, SkillMatchCandidate] = {}
    for c in candidates:
        existing = best_by_skill.get(c.skill.skill_id)
        if existing is None or c.confidence > existing.confidence:
            best_by_skill[c.skill.skill_id] = c

    return sorted(best_by_skill.values(), key=lambda c: c.confidence, reverse=True)


def is_confident(candidates: list[SkillMatchCandidate]) -> bool:
    """True if the top candidate is confident enough, and clearly ahead of
    any rival, that Qwen validation can be skipped."""
    if not candidates:
        return False
    if candidates[0].method in ("EXACT", "ALIAS"):
        return True
    if len(candidates) == 1:
        return candidates[0].confidence >= HIGH_CONFIDENCE_THRESHOLD
    gap = candidates[0].confidence - candidates[1].confidence
    return candidates[0].confidence >= HIGH_CONFIDENCE_THRESHOLD and gap >= 0.08
