from app.db.models.evaluation import ResumeSkill
from app.db.models.resume import Resume
from app.schemas.resume import ResumeStatusResponse
from app.schemas.skills import SkillVerificationItem


def resume_to_schema(resume: Resume) -> ResumeStatusResponse:
    """Built explicitly rather than via ResumeStatusResponse.model_validate --
    the ORM primary key is `Resume.id`, not `resume_id`, and Pydantic's
    from_attributes mode does plain attribute-name matching with no implicit
    aliasing, so model_validate(resume) fails validation on that field."""
    return ResumeStatusResponse(
        resume_id=resume.id,
        filename=resume.filename,
        status=resume.status.value if hasattr(resume.status, "value") else resume.status,
        page_count=resume.page_count,
        failed_stage=resume.failed_stage,
        failure_reason=resume.failure_reason,
        uploaded_at=resume.uploaded_at,
    )


def skill_to_schema(row: ResumeSkill) -> SkillVerificationItem:
    return SkillVerificationItem(
        resume_skill_id=row.id,
        skill_id=row.skill_id,
        canonical_name=row.canonical_name,
        detected_text=row.detected_text,
        confidence=row.confidence,
        detection_method=row.detection_method.value if hasattr(row.detection_method, "value") else row.detection_method,
        verification_status=row.verification_status.value if hasattr(row.verification_status, "value") else row.verification_status,
        source_chunk_ids=row.source_chunk_ids or [],
        user_modified=row.user_modified,
    )
