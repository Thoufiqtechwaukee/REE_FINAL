import enum
import uuid
from datetime import datetime, UTC

from sqlalchemy import DateTime


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


DATETIME_UTC = DateTime(timezone=True)


class CanonicalSection(str, enum.Enum):
    CONTACT = "CONTACT"
    SUMMARY = "SUMMARY"
    SKILLS = "SKILLS"
    EXPERIENCE = "EXPERIENCE"
    PROJECTS = "PROJECTS"
    EDUCATION = "EDUCATION"
    CERTIFICATIONS = "CERTIFICATIONS"
    ACHIEVEMENTS = "ACHIEVEMENTS"
    AWARDS = "AWARDS"
    PUBLICATIONS = "PUBLICATIONS"
    INTERESTS = "INTERESTS"
    OTHER = "OTHER"
