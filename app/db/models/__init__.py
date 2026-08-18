"""Import every model module so Base.metadata is fully populated for Alembic
autogenerate and create_all -- cross-file FKs (e.g. ResumeChunk -> Role) need
every mapped class registered before metadata is used."""
from app.db.models.role import Role, RoleAlias, RoleDomain, RoleLevel, RoleSkillRelation
from app.db.models.skill import (
    TechnicalSkill,
    TechnicalSkillAlias,
    TechnicalSkillCategory,
    TechnicalSkillRelation,
)
from app.db.models.resume import (
    Resume,
    ResumeChunk,
    ResumeExtraction,
    ResumeGap,
    ResumeSection,
)
from app.db.models.evaluation import (
    ResumeAgentRun,
    ResumeEvaluation,
    ResumeEvaluationScore,
    ResumeExperience,
    ResumeRecommendation,
    ResumeSkill,
    ResumeSkillEvidence,
)

__all__ = [
    "Role",
    "RoleAlias",
    "RoleDomain",
    "RoleLevel",
    "RoleSkillRelation",
    "TechnicalSkill",
    "TechnicalSkillAlias",
    "TechnicalSkillCategory",
    "TechnicalSkillRelation",
    "Resume",
    "ResumeChunk",
    "ResumeExtraction",
    "ResumeGap",
    "ResumeSection",
    "ResumeAgentRun",
    "ResumeEvaluation",
    "ResumeEvaluationScore",
    "ResumeExperience",
    "ResumeRecommendation",
    "ResumeSkill",
    "ResumeSkillEvidence",
]
