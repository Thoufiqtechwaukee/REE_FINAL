"""
ScoreEngine (spec §34/§56). Every point value is computed here in Python;
Qwen never writes to a score field anywhere in this codebase (Growth and
Completeness's Qwen calls return categorical verdicts only -- see
agents/growth.py, agents/completeness.py -- which this module or those
modules map to points via a fixed rubric). Experience and Evidence are fully
deterministic once their inputs (ResumeExperience rows, ResumeSkillEvidence
rows) exist.
"""
import re
from dataclasses import dataclass
from datetime import date

from app.db.models.evaluation import EvidenceStrength, EvidenceType, ResumeExperience, ResumeSkill

EXPERIENCE_MAX_POINTS = {
    "documented_magnitude": 8,
    "role_depth": 5,
    "skill_supported_experience": 5,
    "current_freshness": 4,
    "claimed_vs_calculated_consistency": 3,
}
EVIDENCE_CORE_MAX = 12
EVIDENCE_SUPPORTING_MAX = 8
EVIDENCE_PROJECT_BONUS_MAX = 5

_CLAIMED_YEARS_RE = re.compile(r"(\d{1,2})\+?\s*years?(?:\s+of)?\s+experience", re.IGNORECASE)

_EXPERIENCE_LINKED_TYPES = {
    EvidenceType.EXPLICIT_IMPLEMENTATION,
    EvidenceType.RESPONSIBILITY_USAGE,
    EvidenceType.PROJECT_USAGE,
}


@dataclass
class SubScore:
    name: str
    points: float
    points_max: float
    explanation: str = ""


@dataclass
class CategoryScore:
    category: str
    total: float
    sub_scores: list[SubScore]


def score_experience(
    experiences: list[ResumeExperience],
    verified_skills: list[ResumeSkill],
    evidence_by_resume_skill_id: dict[str, list],
    total_experience_months: int,
    summary_text: str,
    today: date,
) -> CategoryScore:
    m = EXPERIENCE_MAX_POINTS
    if not experiences:
        return CategoryScore("EXPERIENCE", 0.0, [SubScore(k, 0.0, v, "No dated experience found") for k, v in m.items()])

    dated_ratio = sum(1 for e in experiences if e.start_date and e.end_date) / len(experiences)
    magnitude_score = min(1.0, total_experience_months / 24.0)
    documented_points = round(m["documented_magnitude"] * (0.5 * dated_ratio + 0.5 * magnitude_score), 2)

    avg_responsibilities = sum(len(e.responsibilities) for e in experiences) / len(experiences)
    depth_points = round(m["role_depth"] * min(1.0, avg_responsibilities / 5.0), 2)

    if verified_skills:
        supported = 0
        for rs in verified_skills:
            rows = evidence_by_resume_skill_id.get(rs.id, [])
            if any(r.evidence_type in _EXPERIENCE_LINKED_TYPES for r in rows):
                supported += 1
        skill_support_ratio = supported / len(verified_skills)
    else:
        skill_support_ratio = 0.0
    skill_points = round(m["skill_supported_experience"] * skill_support_ratio, 2)

    dated = [e for e in experiences if e.end_date]
    most_recent_end = max((e.end_date for e in dated), default=None)
    has_current = any(e.is_current for e in experiences)
    if has_current or (most_recent_end and (today - most_recent_end).days < 180):
        freshness_points = float(m["current_freshness"])
    elif most_recent_end:
        staleness_years = (today - most_recent_end).days / 365.0
        freshness_points = round(max(0.0, m["current_freshness"] * (1 - staleness_years / 3.0)), 2)
    else:
        freshness_points = 0.0

    consistency_points = float(m["claimed_vs_calculated_consistency"])
    claimed_match = _CLAIMED_YEARS_RE.search(summary_text or "")
    if claimed_match:
        claimed_years = int(claimed_match.group(1))
        actual_years = total_experience_months / 12.0
        if abs(actual_years - claimed_years) >= 3:
            consistency_points = max(0.0, consistency_points - 2.0)

    sub_scores = [
        SubScore("documented_magnitude", documented_points, m["documented_magnitude"], f"{total_experience_months} total merged months"),
        SubScore("role_depth", depth_points, m["role_depth"], f"avg {avg_responsibilities:.1f} responsibilities/role"),
        SubScore("skill_supported_experience", skill_points, m["skill_supported_experience"], f"{skill_support_ratio*100:.0f}% of verified skills experience-linked"),
        SubScore("current_freshness", freshness_points, m["current_freshness"], "Current or recently active" if freshness_points >= m["current_freshness"] else "Most recent role is not recent"),
        SubScore("claimed_vs_calculated_consistency", consistency_points, m["claimed_vs_calculated_consistency"], "Claimed vs. calculated experience"),
    ]
    total = min(25.0, round(sum(s.points for s in sub_scores), 2))
    return CategoryScore("EXPERIENCE", total, sub_scores)


def score_evidence(verified_skills: list[ResumeSkill], strength_by_resume_skill_id: dict[str, EvidenceStrength], has_project_evidence_by_id: dict[str, bool]) -> CategoryScore:
    if not verified_skills:
        return CategoryScore("EVIDENCE", 0.0, [SubScore("no_skills", 0.0, 25, "No verified skills to evaluate")])

    strong = sum(1 for rs in verified_skills if strength_by_resume_skill_id.get(rs.id) == EvidenceStrength.STRONG)
    moderate = sum(1 for rs in verified_skills if strength_by_resume_skill_id.get(rs.id) == EvidenceStrength.MODERATE)
    n = len(verified_skills)

    strong_ratio = strong / n
    supported_ratio = (strong + moderate) / n
    core_points = round(EVIDENCE_CORE_MAX * strong_ratio, 2)
    supporting_points = round(EVIDENCE_SUPPORTING_MAX * supported_ratio, 2)

    project_backed_count = sum(1 for rs in verified_skills if has_project_evidence_by_id.get(rs.id))
    if project_backed_count >= 3:
        project_points = EVIDENCE_PROJECT_BONUS_MAX
    elif project_backed_count >= 1:
        project_points = 3
    else:
        project_points = 2

    sub_scores = [
        SubScore("core_skill_evidence", core_points, EVIDENCE_CORE_MAX, f"{strong}/{n} skills with STRONG evidence"),
        SubScore("supporting_evidence", supporting_points, EVIDENCE_SUPPORTING_MAX, f"{strong+moderate}/{n} skills with STRONG or MODERATE evidence"),
        SubScore("project_evidence", project_points, EVIDENCE_PROJECT_BONUS_MAX, f"{project_backed_count} skills with project-linked evidence"),
    ]
    total = min(25.0, round(sum(s.points for s in sub_scores), 2))
    return CategoryScore("EVIDENCE", total, sub_scores)


@dataclass
class FinalScore:
    completeness: float
    growth: float
    evidence: float
    experience: float

    @property
    def total(self) -> float:
        return round(self.completeness + self.growth + self.evidence + self.experience, 2)
