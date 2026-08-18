"""
Deterministic recommendation generator (spec §19/§39/§57), independent of
Qwen -- produces concrete, evidence-grounded recruiter/candidate
recommendations from the already-computed structured findings, not from a
free-form LLM pass.
"""
import re
from dataclasses import dataclass

from app.agents.evidence import SkillEvidenceResult
from app.agents.growth import GrowthResult
from app.db.models.evaluation import EvidenceStrength, ResumeExperience

_METRIC_RE = re.compile(r"\b\d+%|\$\d+|\b\d+\s*(?:users|clients|customers|projects|systems|applications|teams|servers)\b", re.IGNORECASE)


@dataclass
class Recommendation:
    priority: int
    title: str
    category: str
    description: str
    audience: str = "BOTH"


def build_recommendations(
    evidence_results: list[SkillEvidenceResult],
    growth_result: GrowthResult,
    experiences: list[ResumeExperience],
    completeness_warnings: list[str],
) -> list[Recommendation]:
    recs: list[Recommendation] = []

    weak_or_none = [r for r in evidence_results if r.strength in (EvidenceStrength.WEAK, EvidenceStrength.NONE)]
    if weak_or_none:
        names = ", ".join(r.resume_skill.canonical_name for r in weak_or_none[:5])
        recs.append(
            Recommendation(
                priority=1,
                title="Strengthen evidence for listed skills",
                category="EVIDENCE",
                description=(
                    f"The following verified skills have little or no supporting evidence in the "
                    f"experience/project text: {names}. Add specific examples of how these were used."
                ),
                audience="CANDIDATE",
            )
        )

    all_bullets = [b for e in experiences for b in e.responsibilities]
    quantified = sum(1 for b in all_bullets if _METRIC_RE.search(b))
    if all_bullets and quantified / len(all_bullets) < 0.2:
        recs.append(
            Recommendation(
                priority=2,
                title="Quantify impact with metrics",
                category="COMPLETENESS",
                description=(
                    "Most responsibility bullets lack quantifiable outcomes (percentages, counts, "
                    "dollar amounts). Adding concrete metrics makes impact easier to assess."
                ),
                audience="CANDIDATE",
            )
        )

    if growth_result.available:
        leadership_dim = next((d for d in growth_result.dimensions if d.dimension == "leadership"), None)
        if leadership_dim and leadership_dim.label in ("NONE", "LOW"):
            recs.append(
                Recommendation(
                    priority=3,
                    title="Highlight leadership and architectural decisions",
                    category="GROWTH",
                    description=(
                        "The resume shows limited explicit evidence of mentoring, leading others, or "
                        "architecture-level decision-making. If applicable, make this scope visible."
                    ),
                    audience="CANDIDATE",
                )
            )

    for warning in completeness_warnings:
        if "certification" in warning.lower():
            recs.append(
                Recommendation(
                    priority=4,
                    title="Consider adding relevant certifications",
                    category="COMPLETENESS",
                    description=warning,
                    audience="CANDIDATE",
                )
            )
            break

    return sorted(recs, key=lambda r: r.priority)[:4]
