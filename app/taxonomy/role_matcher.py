"""
Role normalization pipeline (spec §29): exact -> alias -> fuzzy -> Nomic
semantic, same shape as skill_matcher.py. Also implements seniority-level
classification (spec §28's 16-level ladder) using the priority-ordered,
ambiguity-aware pattern proven in the prior C# system: narrow/specific
keywords (Intern/Junior) are checked before broad ones (Director/Manager) so
a domain qualifier never lets a seniority word "promote" a title it doesn't
belong to, and genuinely ambiguous bare words (Head/Founder/Owner) are
flagged for Qwen escalation rather than silently ranked -- this is exactly
the fix for a real observed bug where "Project Head" (a single student
project) matched the same bucket as "Director"/"VP" purely by substring.
"""
import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from app.db.models.role import Role, RoleAlias, RoleLevel
from app.retrieval.skill_retrieval import search_role_candidates
from app.taxonomy.skill_matcher import loose_key

FUZZY_THRESHOLD = 85
SEMANTIC_THRESHOLD = 0.55
HIGH_CONFIDENCE_THRESHOLD = 0.90


@dataclass
class RoleMatchCandidate:
    role: Role
    confidence: float
    method: str  # EXACT | ALIAS | FUZZY | SEMANTIC


def _catalog_lookup_maps(db: Session) -> tuple[dict[str, Role], dict[str, Role]]:
    roles = db.query(Role).filter(Role.active == True).all()
    exact_map: dict[str, Role] = {loose_key(r.canonical_title): r for r in roles}

    aliases = db.query(RoleAlias).join(Role).filter(Role.active == True).all()
    fuzzy_universe: dict[str, Role] = {r.canonical_title.lower(): r for r in roles}
    alias_map: dict[str, Role] = {}
    for a in aliases:
        alias_map[loose_key(a.alias_text)] = a.role
        fuzzy_universe.setdefault(a.alias_text.lower(), a.role)

    return exact_map, alias_map, fuzzy_universe


async def find_candidates(db: Session, raw_title: str) -> list[RoleMatchCandidate]:
    if not raw_title or not raw_title.strip():
        return []

    exact_map, alias_map, fuzzy_universe = _catalog_lookup_maps(db)
    key = loose_key(raw_title)

    if key in exact_map:
        return [RoleMatchCandidate(role=exact_map[key], confidence=1.0, method="EXACT")]
    if key in alias_map:
        return [RoleMatchCandidate(role=alias_map[key], confidence=0.95, method="ALIAS")]

    fuzzy_candidate = None
    match = process.extractOne(raw_title, fuzzy_universe.keys(), scorer=fuzz.WRatio, score_cutoff=FUZZY_THRESHOLD)
    if match:
        matched_key, score, _ = match
        fuzzy_candidate = RoleMatchCandidate(role=fuzzy_universe[matched_key], confidence=score / 100.0, method="FUZZY")
        if fuzzy_candidate.confidence >= HIGH_CONFIDENCE_THRESHOLD:
            return [fuzzy_candidate]

    semantic_hits = await search_role_candidates(db, raw_title, top_k=5, min_similarity=SEMANTIC_THRESHOLD)
    semantic_candidates = [RoleMatchCandidate(role=r, confidence=s, method="SEMANTIC") for r, s in semantic_hits]

    candidates = ([fuzzy_candidate] if fuzzy_candidate else []) + semantic_candidates
    best_by_role: dict[str, RoleMatchCandidate] = {}
    for c in candidates:
        existing = best_by_role.get(c.role.role_id)
        if existing is None or c.confidence > existing.confidence:
            best_by_role[c.role.role_id] = c
    return sorted(best_by_role.values(), key=lambda c: c.confidence, reverse=True)


def is_confident(candidates: list[RoleMatchCandidate]) -> bool:
    if not candidates:
        return False
    if candidates[0].method in ("EXACT", "ALIAS"):
        return True
    if len(candidates) == 1:
        return candidates[0].confidence >= HIGH_CONFIDENCE_THRESHOLD
    gap = candidates[0].confidence - candidates[1].confidence
    return candidates[0].confidence >= HIGH_CONFIDENCE_THRESHOLD and gap >= 0.08


# --- Seniority classification (spec §28) ---------------------------------

_LEVEL_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(intern|apprentice)\b", re.IGNORECASE), "Intern"),
    (re.compile(r"\btrainee\b", re.IGNORECASE), "Trainee"),
    (re.compile(r"\bjunior\b", re.IGNORECASE), "Junior"),
    (re.compile(r"\bassociate\b", re.IGNORECASE), "Associate"),
    (re.compile(r"\b(chief|ceo|cto|cfo|coo|president)\b", re.IGNORECASE), "C-Level"),
    (re.compile(r"\b(vp|vice[\s-]president)\b", re.IGNORECASE), "VP"),
    (re.compile(r"\bhead\s+of\b", re.IGNORECASE), "Head"),
    (re.compile(r"\bdirector\b", re.IGNORECASE), "Director"),
    (re.compile(r"\b(senior\s+manager|sr\.?\s*manager)\b", re.IGNORECASE), "Senior Manager"),
    (re.compile(r"\bmanager\b", re.IGNORECASE), "Manager"),
    (re.compile(r"\barchitect\b", re.IGNORECASE), "Architect"),
    (re.compile(r"\bstaff\b", re.IGNORECASE), "Staff"),
    (re.compile(r"\bprincipal\b", re.IGNORECASE), "Principal"),
    (re.compile(r"\b(lead|scrum\s*master|product\s*owner)\b", re.IGNORECASE), "Lead"),
    (re.compile(r"\b(senior|sr\.?)\b", re.IGNORECASE), "Senior"),
]

# Bare words that are genuinely ambiguous without a qualifying phrase --
# "Head of Engineering" is caught by the qualified rule above before this is
# ever reached; a bare "Project Head"/"Founder"/"Owner" is not.
_AMBIGUOUS_BARE_WORDS = re.compile(r"\b(head|founder|co-founder|owner)\b", re.IGNORECASE)

DEFAULT_LEVEL_NAME = "Mid-Level"


@dataclass
class SeniorityResult:
    level_id: int | None
    level_name: str | None
    confidence: float
    is_ambiguous: bool


def classify_seniority(title: str, level_by_name: dict[str, int], previous_level_id: int | None = None) -> SeniorityResult:
    if not title or not title.strip():
        level_id = level_by_name.get(DEFAULT_LEVEL_NAME)
        return SeniorityResult(level_id, DEFAULT_LEVEL_NAME, 0.4, False)

    for pattern, name in _LEVEL_RULES:
        if pattern.search(title):
            return SeniorityResult(level_by_name.get(name), name, 0.9, False)

    if _AMBIGUOUS_BARE_WORDS.search(title):
        fallback_id = previous_level_id if previous_level_id is not None else level_by_name.get(DEFAULT_LEVEL_NAME)
        return SeniorityResult(fallback_id, None, 0.3, True)

    level_id = level_by_name.get(DEFAULT_LEVEL_NAME)
    return SeniorityResult(level_id, DEFAULT_LEVEL_NAME, 0.7, False)


def load_level_by_name(db: Session) -> dict[str, int]:
    return {lvl.name: lvl.id for lvl in db.query(RoleLevel).all()}
