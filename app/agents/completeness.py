"""
Completeness category (spec §41-42). Structural checks in Python; qualitative
checks (staleness, genericness, section applicability, contradictions) via
Qwen -- and per spec §42, a section that's legitimately not applicable (e.g.
Certifications for a role family that doesn't typically expect them) must not
be penalized as if it were genuinely missing.
"""
import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agents.prompts.completeness import COMPLETENESS_PROMPT
from app.agents.qwen_client import call_chat_json
from app.core.dates import calculate_months_between
from app.db.models.evaluation import ResumeExperience, ResumeSkill
from app.db.models.resume import ChunkType, ResumeChunk, ResumeSection

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d{1,3}[\s-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
_CLAIMED_YEARS_RE = re.compile(r"(\d{1,2})\+?\s*years?(?:\s+of)?\s+experience", re.IGNORECASE)

MAX_POINTS = {
    "contact": 2,
    "summary": 3,
    "experience_detail": 5,
    "technical_skills": 3,
    "education": 2,
    "projects": 2,
    "certifications": 2,
    "achievements": 1,
    "date_company_role_clarity": 2,
    "freshness_consistency": 3,
}
_NOT_APPLICABLE_CREDIT_FRACTION = 0.7


@dataclass
class SubScore:
    name: str
    points: float
    points_max: float
    explanation: str


@dataclass
class CompletenessResult:
    sub_scores: list[SubScore]
    total_score: float
    warnings: list[str] = field(default_factory=list)


async def analyze_completeness(
    db: Session,
    resume_id: str,
    experiences: list[ResumeExperience],
    verified_skills: list[ResumeSkill],
    total_experience_months: int,
) -> CompletenessResult:
    chunks = db.query(ResumeChunk).filter(ResumeChunk.resume_id == resume_id).all()
    sections = db.query(ResumeSection).filter(ResumeSection.resume_id == resume_id).all()
    present_sections = {s.canonical_section for s in sections}

    contact_text = "\n".join(c.original_text for c in chunks if _type(c) == ChunkType.CONTACT.value)
    summary_chunks = [c for c in chunks if _type(c) == ChunkType.SUMMARY.value]
    summary_text = "\n".join(c.original_text for c in summary_chunks)
    has_certifications = any(_type(c) == ChunkType.CERTIFICATION.value for c in chunks)
    has_projects = any(_type(c) == ChunkType.PROJECT.value or _type(c) == ChunkType.EXPERIENCE_PROJECT.value for c in chunks)
    has_achievements = any(_type(c) == ChunkType.ACHIEVEMENT.value for c in chunks)
    has_education = "EDUCATION" in present_sections

    most_recent = max(experiences, key=lambda e: e.end_date or e.start_date, default=None) if experiences else None
    actual_years = round(total_experience_months / 12, 1)

    qwen_data = await _run_qualitative_check(
        summary_text, most_recent, actual_years, has_certifications, has_projects, has_achievements
    )

    sub_scores: list[SubScore] = []
    warnings: list[str] = []

    # Contact
    has_email = bool(_EMAIL_RE.search(contact_text))
    has_phone = bool(_PHONE_RE.search(contact_text))
    contact_points = MAX_POINTS["contact"] if (has_email or has_phone) else 0
    sub_scores.append(SubScore("contact", contact_points, MAX_POINTS["contact"], "Email or phone present" if contact_points else "No contact information found"))

    # Summary
    if summary_text and len(summary_text) > 20:
        summary_points = MAX_POINTS["summary"]
        if qwen_data and qwen_data.get("summary_outdated"):
            summary_points -= 1.5
            warnings.append(qwen_data.get("summary_reason") or "Summary appears outdated relative to current experience.")
        if qwen_data and qwen_data.get("summary_generic"):
            summary_points -= 1.0
        summary_points = max(0.0, summary_points)
    else:
        summary_points = 0.0
        warnings.append("No professional summary found.")
    sub_scores.append(SubScore("summary", round(summary_points, 2), MAX_POINTS["summary"], "Summary quality"))

    # Experience detail
    if experiences:
        detail_ratio = sum(1 for e in experiences if len(e.responsibilities) >= 2 or e.company != "Unknown") / len(experiences)
    else:
        detail_ratio = 0.0
        warnings.append("No employment history found.")
    sub_scores.append(SubScore("experience_detail", round(detail_ratio * MAX_POINTS["experience_detail"], 2), MAX_POINTS["experience_detail"], "Fraction of roles with real detail"))

    # Technical skills
    skill_points = MAX_POINTS["technical_skills"] if len(verified_skills) >= 3 else round(len(verified_skills) / 3 * MAX_POINTS["technical_skills"], 2)
    sub_scores.append(SubScore("technical_skills", skill_points, MAX_POINTS["technical_skills"], f"{len(verified_skills)} verified skills"))

    # Education
    sub_scores.append(SubScore("education", MAX_POINTS["education"] if has_education else 0, MAX_POINTS["education"], "Education section present" if has_education else "No education section found"))

    # Projects / Certifications / Achievements -- applicability-aware
    for key, present, judgment_key, max_pts in [
        ("projects", has_projects, "projects", MAX_POINTS["projects"]),
        ("certifications", has_certifications, "certifications", MAX_POINTS["certifications"]),
        ("achievements", has_achievements, "achievements", MAX_POINTS["achievements"]),
    ]:
        if present:
            points = max_pts
            explanation = f"{key.capitalize()} present"
        else:
            applicability = (qwen_data or {}).get("section_applicability", {}).get(judgment_key)
            if applicability == "NOT_EXPECTED":
                points = round(max_pts * _NOT_APPLICABLE_CREDIT_FRACTION, 2)
                explanation = f"{key.capitalize()} absent but judged not applicable for this candidate's profile"
            else:
                points = 0.0
                explanation = f"{key.capitalize()} absent and expected for this candidate's profile"
                warnings.append(f"No {key} found; this is typically expected for this candidate's profile.")
        sub_scores.append(SubScore(key, points, max_pts, explanation))

    # Date/company/role clarity
    if experiences:
        clarity_ratio = sum(1 for e in experiences if e.company != "Unknown" and e.raw_title != "Unknown" and e.start_date) / len(experiences)
    else:
        clarity_ratio = 0.0
    sub_scores.append(SubScore("date_company_role_clarity", round(clarity_ratio * MAX_POINTS["date_company_role_clarity"], 2), MAX_POINTS["date_company_role_clarity"], "Fraction of roles with clear company/title/dates"))

    # Freshness/consistency
    freshness_points = MAX_POINTS["freshness_consistency"]
    claimed_match = _CLAIMED_YEARS_RE.search(summary_text)
    if claimed_match:
        claimed_years = int(claimed_match.group(1))
        if actual_years - claimed_years >= 3:
            freshness_points -= 1.5
            warnings.append(
                f"Summary claims {claimed_years}+ years of experience, but documented experience "
                f"totals approximately {actual_years} years -- a discrepancy worth clarifying."
            )
    if qwen_data and qwen_data.get("contradictions"):
        freshness_points -= min(1.5, 0.5 * len(qwen_data["contradictions"]))
        warnings.extend(qwen_data["contradictions"])
    freshness_points = max(0.0, round(freshness_points, 2))
    sub_scores.append(SubScore("freshness_consistency", freshness_points, MAX_POINTS["freshness_consistency"], "Consistency between claims and documented evidence"))

    total = min(25.0, round(sum(s.points for s in sub_scores), 2))
    return CompletenessResult(sub_scores=sub_scores, total_score=total, warnings=warnings)


def _type(chunk: ResumeChunk) -> str:
    return chunk.chunk_type.value if hasattr(chunk.chunk_type, "value") else chunk.chunk_type


async def _run_qualitative_check(
    summary_text: str, most_recent: ResumeExperience | None, actual_years: float,
    has_certifications: bool, has_projects: bool, has_achievements: bool,
) -> dict | None:
    payload = {
        "summary_text": summary_text,
        "most_recent_title": most_recent.raw_title if most_recent else None,
        "most_recent_role_family": most_recent.role_family if most_recent else None,
        "actual_total_years_experience": actual_years,
        "sections_absent": [
            name for name, present in [("certifications", has_certifications), ("projects", has_projects), ("achievements", has_achievements)] if not present
        ],
    }
    data = await call_chat_json(COMPLETENESS_PROMPT, json.dumps(payload))
    return data if isinstance(data, dict) else None
