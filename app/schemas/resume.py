from datetime import datetime

from pydantic import BaseModel


class ResumeStatusResponse(BaseModel):
    resume_id: str
    filename: str
    status: str
    page_count: int
    failed_stage: str | None = None
    failure_reason: str | None = None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class ResumeUploadResponse(BaseModel):
    resume: ResumeStatusResponse
    skills: list["SkillVerificationItem"]


from app.schemas.skills import SkillVerificationItem  # noqa: E402

ResumeUploadResponse.model_rebuild()
