"""
ResumeEvaluationOrchestrator (spec §65-66). Enforces the hard gate (only
starts from SKILLS_VERIFIED), builds Experience first (Evidence/Growth/
Completeness all depend on it), then runs those three concurrently via
asyncio.gather with per-category failure isolation (spec §52) -- one
category's failure marks it PARTIAL with a stored reason, never crashes the
other two or the whole run.
"""
import asyncio
import hashlib
import logging
import time
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.agents import completeness as completeness_agent
from app.agents import evidence as evidence_agent
from app.agents import experience as experience_agent
from app.agents import final_justification as final_justification_agent
from app.agents import growth as growth_agent
from app.core.dates import format_months_to_years_and_months
from app.core.versioning import CURRENT_VERSIONS
from app.db.models.evaluation import (
    AgentRunStatus,
    EvaluationStatus,
    ResumeAgentRun,
    ResumeEvaluation,
    ResumeEvaluationScore,
    ResumeRecommendation,
    ResumeSkill,
    ResumeSkillEvidence,
    ScoreCategory,
)
from app.db.models.resume import ChunkType, Resume, ResumeChunk, ResumeGap, ResumeStatus
from app.evaluation import scoring
from app.evaluation.recommendations import build_recommendations

logger = logging.getLogger(__name__)


def _record_agent_run(
    db: Session,
    resume_id: str,
    agent_name: str,
    status: AgentRunStatus,
    started_at: datetime,
    started_monotonic: float,
    error: str | None = None,
    evaluation_id: str | None = None,
) -> None:
    """`started_at` is a real wall-clock timestamp for the DB column;
    `started_monotonic` (a `time.monotonic()` reading, not comparable to wall
    clock) is only used to compute an accurate duration even across a system
    clock adjustment. evaluation_id is left None for stages that run before
    the ResumeEvaluation row exists (resume_id alone is sufficient lineage;
    the FK is nullable specifically for this)."""
    db.add(
        ResumeAgentRun(
            resume_id=resume_id,
            evaluation_id=evaluation_id,
            agent_name=agent_name,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            duration_ms=int((time.monotonic() - started_monotonic) * 1000),
            error_message=error,
        )
    )


async def run_full_evaluation(db: Session, resume_id: str) -> dict:
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise ValueError("Resume not found")
    if resume.status not in (ResumeStatus.SKILLS_VERIFIED, ResumeStatus.EVALUATING, ResumeStatus.COMPLETED):
        raise PermissionError(
            f"Evaluation cannot start: skills have not been verified (current status: {resume.status.value})"
        )

    resume.status = ResumeStatus.EVALUATING
    db.commit()

    telemetry: dict = {}
    failed_components: list[str] = []
    t_start = time.monotonic()

    verified_skills = (
        db.query(ResumeSkill)
        .filter(ResumeSkill.resume_id == resume_id, ResumeSkill.verification_status != "USER_REMOVED")
        .all()
    )
    verified_skill_set_hash = _hash_skill_set(verified_skills)

    # --- Experience (must complete before Evidence/Growth/Completeness) ---
    t0 = time.monotonic()
    started_at = datetime.now(timezone.utc)
    try:
        experiences = await experience_agent.build_experience_records(db, resume_id)
        total_months = experience_agent.compute_total_experience_months(experiences)
        experience_agent.detect_gaps(db, resume_id, experiences)
        telemetry["experience_ms"] = int((time.monotonic() - t0) * 1000)
        _record_agent_run(db, resume_id, "experience", AgentRunStatus.SUCCESS, started_at, t0)
    except Exception as exc:
        logger.exception("Experience agent failed for resume %s", resume_id)
        failed_components.append("EXPERIENCE")
        experiences = []
        total_months = 0
        _record_agent_run(db, resume_id, "experience", AgentRunStatus.FAILED, started_at, t0, error=str(exc)[:1000])

    gaps = db.query(ResumeGap).filter(ResumeGap.resume_id == resume_id).all()
    summary_chunks = db.query(ResumeChunk).filter(
        ResumeChunk.resume_id == resume_id, ResumeChunk.chunk_type == ChunkType.SUMMARY.value
    ).all()
    summary_text = "\n".join(c.original_text for c in summary_chunks)

    # --- Evidence / Growth / Completeness concurrently ---
    async def _run_evidence():
        t = time.monotonic()
        started = datetime.now(timezone.utc)
        try:
            result = await evidence_agent.analyze_evidence(db, resume_id)
            telemetry["evidence_ms"] = int((time.monotonic() - t) * 1000)
            _record_agent_run(db, resume_id, "evidence", AgentRunStatus.SUCCESS, started, t)
            return result
        except Exception as exc:
            logger.exception("Evidence agent failed for resume %s", resume_id)
            failed_components.append("EVIDENCE")
            _record_agent_run(db, resume_id, "evidence", AgentRunStatus.FAILED, started, t, error=str(exc)[:1000])
            return None

    async def _run_growth():
        t = time.monotonic()
        started = datetime.now(timezone.utc)
        try:
            result = await growth_agent.analyze_growth(db, resume_id, experiences, verified_skills)
            telemetry["growth_ms"] = int((time.monotonic() - t) * 1000)
            if not result.available:
                failed_components.append("GROWTH")
                _record_agent_run(db, resume_id, "growth", AgentRunStatus.FAILED, started, t, error="Qwen unavailable or unparseable")
            else:
                _record_agent_run(db, resume_id, "growth", AgentRunStatus.SUCCESS, started, t)
            return result
        except Exception as exc:
            logger.exception("Growth agent failed for resume %s", resume_id)
            failed_components.append("GROWTH")
            _record_agent_run(db, resume_id, "growth", AgentRunStatus.FAILED, started, t, error=str(exc)[:1000])
            return None

    async def _run_completeness():
        t = time.monotonic()
        started = datetime.now(timezone.utc)
        try:
            result = await completeness_agent.analyze_completeness(db, resume_id, experiences, verified_skills, total_months)
            telemetry["completeness_ms"] = int((time.monotonic() - t) * 1000)
            _record_agent_run(db, resume_id, "completeness", AgentRunStatus.SUCCESS, started, t)
            return result
        except Exception as exc:
            logger.exception("Completeness agent failed for resume %s", resume_id)
            failed_components.append("COMPLETENESS")
            _record_agent_run(db, resume_id, "completeness", AgentRunStatus.FAILED, started, t, error=str(exc)[:1000])
            return None

    evidence_results, growth_result, completeness_result = await asyncio.gather(
        _run_evidence(), _run_growth(), _run_completeness()
    )

    # --- Scoring (deterministic, Python-only) ---
    evidence_results = evidence_results or []
    strength_by_id = {r.resume_skill.id: r.strength for r in evidence_results}
    has_project_by_id = {
        r.resume_skill.id: any(row.evidence_type.value in ("PROJECT_USAGE", "EXPLICIT_IMPLEMENTATION") for row in r.evidence_rows)
        for r in evidence_results
    }
    evidence_score_obj = scoring.score_evidence(verified_skills, strength_by_id, has_project_by_id)

    evidence_by_resume_skill_id: dict[str, list[ResumeSkillEvidence]] = {}
    for rs in verified_skills:
        rows = db.query(ResumeSkillEvidence).filter(ResumeSkillEvidence.resume_skill_id == rs.id).all()
        evidence_by_resume_skill_id[rs.id] = rows

    experience_score_obj = scoring.score_experience(
        experiences, verified_skills, evidence_by_resume_skill_id, total_months, summary_text, date.today()
    )

    growth_score_value = growth_result.total_score if growth_result and growth_result.available else 0.0
    completeness_score_value = completeness_result.total_score if completeness_result else 0.0

    final_score = scoring.FinalScore(
        completeness=completeness_score_value,
        growth=growth_score_value,
        evidence=evidence_score_obj.total,
        experience=experience_score_obj.total,
    )

    # --- Final justification ---
    t0 = time.monotonic()
    experience_summary = (
        f"The candidate has approximately {format_months_to_years_and_months(total_months)} of "
        f"documented professional experience across {len(experiences)} role(s)."
    )
    evidence_highlights = [
        f"{r.resume_skill.canonical_name}: {r.strength.value}" for r in evidence_results[:8]
    ]
    justification = await final_justification_agent.generate_final_justification(
        completeness_score_value, growth_score_value, evidence_score_obj.total, experience_score_obj.total, final_score.total,
        completeness_result.warnings if completeness_result else [],
        growth_result.observations if growth_result and growth_result.available else [],
        growth_result.interview_preparation if growth_result and growth_result.available else [],
        evidence_highlights,
        experience_summary,
    )
    telemetry["final_justification_ms"] = int((time.monotonic() - t0) * 1000)

    recommendations = build_recommendations(
        evidence_results, growth_result if growth_result else growth_agent.GrowthResult(False, [], 0, [], []),
        experiences, completeness_result.warnings if completeness_result else [],
    )

    telemetry["total_ms"] = int((time.monotonic() - t_start) * 1000)
    telemetry["verified_skill_count"] = len(verified_skills)
    telemetry["failed_components"] = failed_components

    status = EvaluationStatus.COMPLETED if not failed_components else EvaluationStatus.PARTIAL

    evaluation = ResumeEvaluation(
        resume_id=resume_id,
        pdf_hash=resume.pdf_hash,
        verified_skill_set_hash=verified_skill_set_hash,
        completeness_score=completeness_score_value,
        growth_score=growth_score_value,
        evidence_score=evidence_score_obj.total,
        experience_score=experience_score_obj.total,
        total_score=final_score.total,
        status=status,
        failed_components=failed_components,
        overall_assessment=justification.get("overall_assessment"),
        strengths=justification.get("strengths", []),
        weaknesses=justification.get("weaknesses", []),
        key_risks=justification.get("key_risks", []),
        interview_preparation=justification.get("interview_preparation", []),
        telemetry=telemetry,
        **CURRENT_VERSIONS.as_dict(),
    )
    db.add(evaluation)
    db.flush()

    for sub in experience_score_obj.sub_scores:
        db.add(ResumeEvaluationScore(evaluation_id=evaluation.id, category=ScoreCategory.EXPERIENCE, sub_dimension=sub.name, points_awarded=sub.points, points_max=sub.points_max, explanation=sub.explanation))
    for sub in evidence_score_obj.sub_scores:
        db.add(ResumeEvaluationScore(evaluation_id=evaluation.id, category=ScoreCategory.EVIDENCE, sub_dimension=sub.name, points_awarded=sub.points, points_max=sub.points_max, explanation=sub.explanation))
    if completeness_result:
        for sub in completeness_result.sub_scores:
            db.add(ResumeEvaluationScore(evaluation_id=evaluation.id, category=ScoreCategory.COMPLETENESS, sub_dimension=sub.name, points_awarded=sub.points, points_max=sub.points_max, explanation=sub.explanation))
    if growth_result and growth_result.available:
        for dim in growth_result.dimensions:
            db.add(ResumeEvaluationScore(evaluation_id=evaluation.id, category=ScoreCategory.GROWTH, sub_dimension=dim.dimension, label=dim.label, points_awarded=dim.points, points_max=dim.points_max, explanation=dim.note, source_chunk_ids=dim.chunk_ids))

    for rec in recommendations:
        db.add(ResumeRecommendation(evaluation_id=evaluation.id, priority=rec.priority, title=rec.title, category=rec.category, description=rec.description, audience=rec.audience))

    resume.status = ResumeStatus.PARTIAL if failed_components else ResumeStatus.COMPLETED
    db.commit()

    return evaluation_to_response(db, evaluation)


def _hash_skill_set(verified_skills: list[ResumeSkill]) -> str:
    key = "|".join(sorted(f"{rs.skill_id}:{rs.verification_status.value}" for rs in verified_skills))
    return hashlib.sha256(key.encode()).hexdigest()


def evaluation_to_response(db: Session, evaluation: ResumeEvaluation) -> dict:
    scores = db.query(ResumeEvaluationScore).filter(ResumeEvaluationScore.evaluation_id == evaluation.id).all()
    recs = db.query(ResumeRecommendation).filter(ResumeRecommendation.evaluation_id == evaluation.id).order_by(ResumeRecommendation.priority).all()

    def _by_category(cat: ScoreCategory):
        return [
            {"sub_dimension": s.sub_dimension, "label": s.label, "points": s.points_awarded, "points_max": s.points_max, "explanation": s.explanation}
            for s in scores if s.category == cat
        ]

    return {
        "evaluation_id": evaluation.id,
        "resume_id": evaluation.resume_id,
        "status": evaluation.status.value if hasattr(evaluation.status, "value") else evaluation.status,
        "scores": {
            "completeness": evaluation.completeness_score,
            "growth": evaluation.growth_score,
            "evidence": evaluation.evidence_score,
            "experience": evaluation.experience_score,
            "total": evaluation.total_score,
        },
        "sub_scores": {
            "completeness": _by_category(ScoreCategory.COMPLETENESS),
            "growth": _by_category(ScoreCategory.GROWTH),
            "evidence": _by_category(ScoreCategory.EVIDENCE),
            "experience": _by_category(ScoreCategory.EXPERIENCE),
        },
        "overall_assessment": evaluation.overall_assessment,
        "strengths": evaluation.strengths,
        "weaknesses": evaluation.weaknesses,
        "key_risks": evaluation.key_risks,
        "interview_preparation": evaluation.interview_preparation,
        "recommendations": [
            {"priority": r.priority, "title": r.title, "category": r.category, "description": r.description, "audience": r.audience}
            for r in recs
        ],
        "failed_components": evaluation.failed_components,
        "telemetry": evaluation.telemetry,
        "versions": CURRENT_VERSIONS.as_dict(),
    }
