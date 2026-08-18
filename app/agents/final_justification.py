"""
FinalJustificationService (spec §57). Composes from the four already-scored
category outputs only -- never independently re-reads the PDF, never invents
new facts, never changes a score. Falls back to a deterministic assembly
(from each category's own warnings/observations) if Qwen is unreachable, so
the pipeline never returns an empty justification.
"""
import json
import logging

from app.agents.prompts.final_justification import FINAL_JUSTIFICATION_PROMPT
from app.agents.qwen_client import call_chat_json

logger = logging.getLogger(__name__)


def _deterministic_fallback(
    completeness_warnings: list[str], growth_observations: list[str], evidence_summary: str, experience_summary: str
) -> dict:
    return {
        "overall_assessment": (
            f"{experience_summary} {evidence_summary} "
            f"{'Growth: ' + growth_observations[0] if growth_observations else ''}"
        ).strip(),
        "strengths": growth_observations[:2],
        "weaknesses": completeness_warnings[:3],
        "key_risks": completeness_warnings[3:5],
    }


async def generate_final_justification(
    completeness_score: float,
    growth_score: float,
    evidence_score: float,
    experience_score: float,
    total_score: float,
    completeness_warnings: list[str],
    growth_observations: list[str],
    growth_interview_prep: list[str],
    evidence_highlights: list[str],
    experience_summary: str,
) -> dict:
    payload = {
        "scores": {
            "completeness": completeness_score,
            "growth": growth_score,
            "evidence": evidence_score,
            "experience": experience_score,
            "total": total_score,
        },
        "completeness_warnings": completeness_warnings,
        "growth_observations": growth_observations,
        "evidence_highlights": evidence_highlights,
        "experience_summary": experience_summary,
    }

    data = await call_chat_json(FINAL_JUSTIFICATION_PROMPT, json.dumps(payload), max_tokens=800)
    if not isinstance(data, dict) or "overall_assessment" not in data:
        logger.warning("Final justification: Qwen unavailable, using deterministic fallback")
        evidence_summary = evidence_highlights[0] if evidence_highlights else "Evidence review completed."
        data = _deterministic_fallback(completeness_warnings, growth_observations, evidence_summary, experience_summary)

    data.setdefault("strengths", [])
    data.setdefault("weaknesses", [])
    data.setdefault("key_risks", [])
    data["interview_preparation"] = growth_interview_prep
    return data
