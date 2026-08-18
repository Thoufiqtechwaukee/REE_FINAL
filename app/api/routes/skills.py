from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import skill_to_schema
from app.core.security import is_valid_resume_id
from app.db.models.skill import TechnicalSkill
from app.db.session import get_db
from app.schemas.skills import CatalogSkillOption, CorrectSkillRequest, FreezeSkillsResponse, SkillVerificationItem
from app.services import skill_verification

router = APIRouter(prefix="/api/resumes/{resume_id}/skills", tags=["skills"])


def _check_id(resume_id: str):
    if not is_valid_resume_id(resume_id):
        raise HTTPException(status_code=400, detail="Invalid resume id")


@router.get("", response_model=list[SkillVerificationItem])
def get_skills(resume_id: str, db: Session = Depends(get_db)):
    _check_id(resume_id)
    rows = skill_verification.list_skills_for_verification(db, resume_id)
    return [skill_to_schema(r) for r in rows]


@router.get("/catalog-search", response_model=list[CatalogSkillOption])
def search_catalog(resume_id: str, q: str, db: Session = Depends(get_db)):
    """Backs the "correct" affordance -- lets the user pick a different
    catalog skill. Search only, never a create-new-skill path."""
    _check_id(resume_id)
    if not q or len(q.strip()) < 2:
        return []
    rows = (
        db.query(TechnicalSkill)
        .filter(TechnicalSkill.active == True, TechnicalSkill.canonical_name.ilike(f"%{q.strip()}%"))
        .limit(20)
        .all()
    )
    return [
        CatalogSkillOption(skill_id=r.skill_id, canonical_name=r.canonical_name, category=r.category.name if r.category else None)
        for r in rows
    ]


@router.post("/{resume_skill_id}/confirm", response_model=SkillVerificationItem)
def confirm_skill(resume_id: str, resume_skill_id: str, db: Session = Depends(get_db)):
    _check_id(resume_id)
    try:
        row = skill_verification.confirm_skill(db, resume_id, resume_skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return skill_to_schema(row)


@router.post("/{resume_skill_id}/correct", response_model=SkillVerificationItem)
def correct_skill(resume_id: str, resume_skill_id: str, body: CorrectSkillRequest, db: Session = Depends(get_db)):
    _check_id(resume_id)
    try:
        row = skill_verification.correct_skill(db, resume_id, resume_skill_id, body.new_skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return skill_to_schema(row)


@router.post("/{resume_skill_id}/remove", response_model=SkillVerificationItem)
def remove_skill(resume_id: str, resume_skill_id: str, db: Session = Depends(get_db)):
    _check_id(resume_id)
    try:
        row = skill_verification.remove_skill(db, resume_id, resume_skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return skill_to_schema(row)


@router.post("/freeze", response_model=FreezeSkillsResponse)
def freeze_skills(resume_id: str, db: Session = Depends(get_db)):
    _check_id(resume_id)
    try:
        verified = skill_verification.freeze_verified_skills(db, resume_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FreezeSkillsResponse(
        resume_id=resume_id, status="SKILLS_VERIFIED", verified_skills=[skill_to_schema(r) for r in verified]
    )
