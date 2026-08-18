"""
Skill verification workflow (spec §22/§23). Confirm / correct / remove only
-- there is no create-skill operation anywhere in this module or its API
route. Freezing is the only thing that advances the state machine past
WAITING_FOR_SKILL_VERIFICATION.
"""
from sqlalchemy.orm import Session

from app.agents.skill_discovery import DiscoveredSkill
from app.db.models.evaluation import DetectionMethod, ResumeSkill, VerificationStatus
from app.db.models.resume import Resume, ResumeStatus
from app.db.models.skill import TechnicalSkill


def persist_discovered_skills(db: Session, resume_id: str, discovered: list[DiscoveredSkill]) -> list[ResumeSkill]:
    """Writes the discovery pipeline's output as AUTO_CONFIRMED candidates --
    this is the state shown to the user in the verification popup, not yet
    final. Safe to call once per resume (idempotent replace)."""
    db.query(ResumeSkill).filter(ResumeSkill.resume_id == resume_id).delete()

    rows = []
    for d in discovered:
        row = ResumeSkill(
            resume_id=resume_id,
            skill_id=d.skill_id,
            detected_text=d.detected_text,
            canonical_name=d.canonical_name,
            confidence=d.confidence,
            detection_method=DetectionMethod(d.detection_method) if d.detection_method in DetectionMethod._value2member_map_ else DetectionMethod.EXACT,
            verification_status=VerificationStatus.AUTO_CONFIRMED,
            source_chunk_ids=sorted(d.source_chunk_ids),
            user_modified=False,
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


def list_skills_for_verification(db: Session, resume_id: str) -> list[ResumeSkill]:
    return (
        db.query(ResumeSkill)
        .filter(ResumeSkill.resume_id == resume_id, ResumeSkill.verification_status != VerificationStatus.USER_REMOVED)
        .all()
    )


def confirm_skill(db: Session, resume_id: str, resume_skill_id: str) -> ResumeSkill:
    row = _get_owned(db, resume_id, resume_skill_id)
    row.verification_status = VerificationStatus.USER_CONFIRMED
    row.user_modified = True
    db.commit()
    return row


def correct_skill(db: Session, resume_id: str, resume_skill_id: str, new_skill_id: str) -> ResumeSkill:
    """The user may only pick another catalog skill -- new_skill_id must
    already exist in TechnicalSkill, enforced here, never accepting arbitrary
    text as a new skill identity."""
    row = _get_owned(db, resume_id, resume_skill_id)
    skill = db.get(TechnicalSkill, new_skill_id)
    if skill is None:
        raise ValueError(f"Unknown catalog skill_id: {new_skill_id}")
    row.skill_id = skill.skill_id
    row.canonical_name = skill.canonical_name
    row.verification_status = VerificationStatus.USER_CORRECTED
    row.user_modified = True
    row.confidence = 1.0
    db.commit()
    return row


def remove_skill(db: Session, resume_id: str, resume_skill_id: str) -> ResumeSkill:
    row = _get_owned(db, resume_id, resume_skill_id)
    row.verification_status = VerificationStatus.USER_REMOVED
    row.user_modified = True
    db.commit()
    return row


def _get_owned(db: Session, resume_id: str, resume_skill_id: str) -> ResumeSkill:
    row = db.get(ResumeSkill, resume_skill_id)
    if row is None or row.resume_id != resume_id:
        raise ValueError("ResumeSkill not found for this resume")
    return row


def freeze_verified_skills(db: Session, resume_id: str) -> list[ResumeSkill]:
    """The hard gate (spec §5): flips SKILLS_VERIFIED and returns the frozen
    VerifiedSkill[] set. Every skill still AUTO_CONFIRMED (the user reviewed
    the list and changed nothing) is implicitly accepted as-is."""
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise ValueError("Resume not found")
    if resume.status not in (ResumeStatus.SKILLS_IDENTIFIED, ResumeStatus.WAITING_FOR_SKILL_VERIFICATION):
        raise ValueError(f"Cannot freeze skills from status {resume.status}")

    verified = list_skills_for_verification(db, resume_id)
    resume.status = ResumeStatus.SKILLS_VERIFIED
    db.commit()
    return verified
