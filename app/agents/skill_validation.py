"""
Qwen skill validation (spec §46): Qwen is NOT the skill catalog. It only ever
selects among catalog candidates already produced by taxonomy/skill_matcher.py
-- it may never invent a skill name. Called only for candidates
skill_matcher.is_confident() judged ambiguous, batched into one call.
"""
import json
from dataclasses import dataclass

from app.agents.prompts.common import build_prompt
from app.agents.qwen_client import call_chat_json
from app.taxonomy.skill_matcher import SkillMatchCandidate

_ROLE = (
    "You are a technical recruiter's skill-identification validator. You choose which "
    "catalog entry (if any) a phrase pulled from a resume actually refers to."
)
_OBJECTIVE = (
    "For each detected phrase, you are given a short list of candidate skills from a "
    "controlled technical skill catalog that a deterministic matching pipeline could not "
    "confidently resolve on its own (ties, or all scores below a high-confidence "
    "threshold). Decide which single candidate (if any) the phrase actually refers to."
)
_RULES = """- You may ONLY choose a skill_id that appears in that item's own candidate list -- you
  may never invent a skill_id, never choose a candidate from a different item's list, and
  never propose a name that isn't already one of the provided candidates.
- If the phrase is not really a technical skill claim (a sentence fragment, a section
  header, a generic word, a location, a language, a soft skill) even though it structurally
  survived this far, choose null.
- If none of the provided candidates plausibly match the phrase, choose null rather than
  picking the closest-sounding wrong one.
- If exactly one candidate is a clear, confident match, choose it even if the phrase's
  spelling differs from the candidate's canonical name (e.g. "VueJS" -> the Vue.js
  candidate)."""
_OUTPUT_SCHEMA = json.dumps(
    {
        "results": [
            {"detected_text": "string", "chosen_skill_id": "string or null", "confidence": "0.0-1.0"}
        ]
    },
    indent=2,
)

_SYSTEM_PROMPT = build_prompt(_ROLE, _OBJECTIVE, _RULES, _OUTPUT_SCHEMA)


@dataclass
class AmbiguousSkillItem:
    detected_text: str
    candidates: list[SkillMatchCandidate]


@dataclass
class SkillValidationVerdict:
    chosen_skill_id: str | None
    confidence: float


async def validate_ambiguous_skills(items: list[AmbiguousSkillItem]) -> dict[str, SkillValidationVerdict]:
    """Keyed by detected_text (first occurrence wins on duplicates). A
    detected_text absent from the result means no verdict could be obtained
    (Qwen unavailable/unparseable) -- callers must treat that as "keep the
    deterministic top candidate as-is", never as an implicit rejection."""
    if not items:
        return {}

    payload = {
        "items": [
            {
                "detected_text": item.detected_text,
                "candidates": [
                    {
                        "skill_id": c.skill.skill_id,
                        "canonical_name": c.skill.canonical_name,
                        "description": c.skill.description or "",
                    }
                    for c in item.candidates
                ],
            }
            for item in items
        ]
    }

    data = await call_chat_json(_SYSTEM_PROMPT, json.dumps(payload))
    verdicts: dict[str, SkillValidationVerdict] = {}
    if not isinstance(data, dict):
        return verdicts

    valid_ids_by_text = {item.detected_text: {c.skill.skill_id for c in item.candidates} for item in items}

    for row in data.get("results", []):
        if not isinstance(row, dict):
            continue
        detected_text = row.get("detected_text")
        if detected_text not in valid_ids_by_text:
            continue
        chosen = row.get("chosen_skill_id")
        if chosen is not None and chosen not in valid_ids_by_text[detected_text]:
            continue  # Qwen proposed something outside its own candidate list -- reject.
        confidence = row.get("confidence")
        verdicts[detected_text] = SkillValidationVerdict(
            chosen_skill_id=chosen, confidence=float(confidence) if isinstance(confidence, (int, float)) else 0.5
        )

    return verdicts
