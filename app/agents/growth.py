"""
Growth category (spec §37-40) -- a major redesign from title-based scoring.
Career progression is only ONE of 9 dimensions; responsibility/ownership/
technical growth, continuity, and current relevance all matter independently.
Qwen returns one ordinal label per dimension (never a number); a fixed table
maps label -> points against that dimension's configured max (spec §40's
exact 4/5/4/3/3/2/2/1/1 = 25 breakdown). If Qwen is unreachable, Growth is
marked unavailable (spec §52) rather than silently defaulting to a score --
this category is fundamentally Qwen-driven by design, unlike Evidence/
Completeness which have a meaningful deterministic core.
"""
import json
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.agents.prompts.growth import GROWTH_PROMPT
from app.agents.qwen_client import call_chat_json
from app.db.models.evaluation import ResumeExperience, ResumeSkill
from app.db.models.resume import ResumeGap

logger = logging.getLogger(__name__)

DIMENSION_MAX = {
    "career_progression": 4,
    "responsibility_growth": 5,
    "technical_growth": 4,
    "skill_alignment": 3,
    "ownership_scope": 3,
    "leadership": 2,
    "continuity": 2,
    "role_domain_evolution": 1,
    "current_state": 1,
}
_LABEL_FRACTIONS = {"NONE": 0.0, "LOW": 0.25, "MODERATE": 0.5, "HIGH": 0.8, "EXCEPTIONAL": 1.0}


@dataclass
class DimensionResult:
    dimension: str
    label: str | None
    points: float
    points_max: float
    chunk_ids: list[str]
    note: str


@dataclass
class GrowthResult:
    available: bool
    dimensions: list[DimensionResult]
    total_score: float
    observations: list[str]
    interview_preparation: list[str]


async def analyze_growth(
    db: Session, resume_id: str, experiences: list[ResumeExperience], verified_skills: list[ResumeSkill]
) -> GrowthResult:
    gaps = db.query(ResumeGap).filter(ResumeGap.resume_id == resume_id).all()

    if not experiences:
        return GrowthResult(available=True, dimensions=_zero_dimensions(), total_score=0.0, observations=[
            "No dated employment history was found, so career growth cannot be assessed."
        ], interview_preparation=[])

    ordered = sorted(experiences, key=lambda e: e.start_date or date.min)
    payload = {
        "roles": [
            {
                "sequence": i,
                "company": e.company,
                "title": e.raw_title,
                "canonical_title": e.canonical_title,
                "seniority_level_id": e.seniority_level_id,
                "start_date": e.start_date.isoformat() if e.start_date else None,
                "end_date": e.end_date.isoformat() if e.end_date else None,
                "is_current": e.is_current,
                "responsibility_level": e.responsibility_level,
                "responsibilities": e.responsibilities,
                "technologies": e.technologies,
                "source_chunk_ids": e.source_chunk_ids,
            }
            for i, e in enumerate(ordered)
        ],
        "verified_skills": [rs.canonical_name for rs in verified_skills],
        "documented_gaps": [
            {"gap_start": g.gap_start.isoformat(), "gap_end": g.gap_end.isoformat(), "duration_months": g.duration_months}
            for g in gaps
        ],
    }

    data = await call_chat_json(GROWTH_PROMPT, json.dumps(payload), max_tokens=1000)
    if not isinstance(data, dict) or "dimensions" not in data:
        logger.warning("Growth agent: Qwen unavailable or unparseable for resume %s", resume_id)
        return GrowthResult(available=False, dimensions=[], total_score=0.0, observations=[], interview_preparation=[])

    dims_raw = data.get("dimensions", {})
    dimensions: list[DimensionResult] = []
    total = 0.0
    for dim_name, max_points in DIMENSION_MAX.items():
        entry = dims_raw.get(dim_name) if isinstance(dims_raw, dict) else None
        label = entry.get("label") if isinstance(entry, dict) else None
        fraction = _LABEL_FRACTIONS.get(label, 0.0)
        points = round(fraction * max_points, 2)
        total += points
        dimensions.append(
            DimensionResult(
                dimension=dim_name,
                label=label,
                points=points,
                points_max=max_points,
                chunk_ids=entry.get("chunk_ids", []) if isinstance(entry, dict) else [],
                note=entry.get("note", "") if isinstance(entry, dict) else "",
            )
        )

    observations = data.get("observations", []) if isinstance(data.get("observations"), list) else []
    interview_prep = data.get("interview_preparation", []) if isinstance(data.get("interview_preparation"), list) else []

    for gap in gaps:
        if not any(gap.gap_start.isoformat() in obs or gap.gap_end.isoformat() in obs for obs in interview_prep):
            interview_prep.append(
                f"The resume indicates a career gap from {gap.gap_start.isoformat()} to "
                f"{gap.gap_end.isoformat()} ({gap.duration_months} months); no reason is "
                f"documented, so be prepared to explain this during interviews."
            )

    return GrowthResult(
        available=True,
        dimensions=dimensions,
        total_score=min(25.0, round(total, 2)),
        observations=observations,
        interview_preparation=interview_prep,
    )


def _zero_dimensions() -> list[DimensionResult]:
    return [
        DimensionResult(dimension=name, label="NONE", points=0.0, points_max=max_points, chunk_ids=[], note="")
        for name, max_points in DIMENSION_MAX.items()
    ]
