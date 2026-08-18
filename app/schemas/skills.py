from pydantic import BaseModel


class SkillVerificationItem(BaseModel):
    resume_skill_id: str
    skill_id: str
    canonical_name: str
    detected_text: str
    confidence: float
    detection_method: str
    verification_status: str
    source_chunk_ids: list[str]
    user_modified: bool

    model_config = {"from_attributes": True}


class CorrectSkillRequest(BaseModel):
    new_skill_id: str


class CatalogSkillOption(BaseModel):
    skill_id: str
    canonical_name: str
    category: str | None = None

    model_config = {"from_attributes": True}


class FreezeSkillsResponse(BaseModel):
    resume_id: str
    status: str
    verified_skills: list[SkillVerificationItem]
