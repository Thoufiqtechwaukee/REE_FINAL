import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.common import new_id, utcnow


class VerificationStatus(str, enum.Enum):
    AUTO_CONFIRMED = "AUTO_CONFIRMED"
    USER_CONFIRMED = "USER_CONFIRMED"
    USER_CORRECTED = "USER_CORRECTED"
    USER_REMOVED = "USER_REMOVED"


class DetectionMethod(str, enum.Enum):
    EXACT = "EXACT"
    ALIAS = "ALIAS"
    FUZZY = "FUZZY"
    SEMANTIC = "SEMANTIC"
    QWEN_VALIDATED = "QWEN_VALIDATED"


class EvidenceType(str, enum.Enum):
    EXPLICIT_IMPLEMENTATION = "EXPLICIT_IMPLEMENTATION"
    PROJECT_USAGE = "PROJECT_USAGE"
    RESPONSIBILITY_USAGE = "RESPONSIBILITY_USAGE"
    TECHNICAL_ENVIRONMENT = "TECHNICAL_ENVIRONMENT"
    CERTIFICATION_ONLY = "CERTIFICATION_ONLY"
    SKILLS_SECTION_ONLY = "SKILLS_SECTION_ONLY"
    INFERRED = "INFERRED"
    NONE = "NONE"


class EvidenceStrength(str, enum.Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NONE = "NONE"


class EvaluationStatus(str, enum.Enum):
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class AgentRunStatus(str, enum.Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ScoreCategory(str, enum.Enum):
    COMPLETENESS = "COMPLETENESS"
    GROWTH = "GROWTH"
    EVIDENCE = "EVIDENCE"
    EXPERIENCE = "EXPERIENCE"


class ResumeExperience(Base):
    __tablename__ = "resume_experiences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), nullable=False, index=True)
    company: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_title: Mapped[str] = mapped_column(String(200), nullable=False)
    canonical_role_id: Mapped[str | None] = mapped_column(ForeignKey("roles.role_id"), nullable=True)
    canonical_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    seniority_level_id: Mapped[int | None] = mapped_column(ForeignKey("role_levels.id"), nullable=True)
    seniority_ambiguous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_months: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    responsibilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    technologies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    projects: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    leadership_indicators: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ownership_indicators: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    responsibility_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_chunk_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResumeSkill(Base):
    """The candidate/verified skill inventory for a resume (spec §22-23).
    Every row always references a real TechnicalSkill catalog row -- there is
    no free-text skill identity anywhere in this table."""

    __tablename__ = "resume_skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("technical_skills.skill_id"), nullable=False, index=True)
    detected_text: Mapped[str] = mapped_column(String(150), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(150), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    detection_method: Mapped[DetectionMethod] = mapped_column(
        Enum(DetectionMethod, native_enum=False, length=20), nullable=False
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, native_enum=False, length=20),
        default=VerificationStatus.AUTO_CONFIRMED,
        nullable=False,
    )
    source_chunk_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    user_modified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class ResumeSkillEvidence(Base):
    __tablename__ = "resume_skill_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resume_skill_id: Mapped[str] = mapped_column(ForeignKey("resume_skills.id"), nullable=False, index=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("resume_chunks.chunk_id"), nullable=False)
    evidence_type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType, native_enum=False, length=30), nullable=False)
    evidence_strength: Mapped[EvidenceStrength] = mapped_column(
        Enum(EvidenceStrength, native_enum=False, length=10), nullable=False
    )
    qwen_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResumeEvaluation(Base):
    __tablename__ = "resume_evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), nullable=False, index=True)
    pdf_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verified_skill_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    completeness_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    growth_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    evidence_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    experience_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)

    status: Mapped[EvaluationStatus] = mapped_column(Enum(EvaluationStatus, native_enum=False, length=20), nullable=False)
    failed_components: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    overall_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    weaknesses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    key_risks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    interview_preparation: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    telemetry: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    skill_taxonomy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    role_taxonomy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(50), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(50), nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(50), nullable=False)
    vector_index_version: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResumeEvaluationScore(Base):
    """Per-sub-dimension lineage rows behind each category total (spec §18's
    score -> finding -> evidence -> chunk -> page lineage requirement)."""

    __tablename__ = "resume_evaluation_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("resume_evaluations.id"), nullable=False, index=True)
    category: Mapped[ScoreCategory] = mapped_column(Enum(ScoreCategory, native_enum=False, length=20), nullable=False)
    sub_dimension: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str | None] = mapped_column(String(30), nullable=True)
    points_awarded: Mapped[float] = mapped_column(Float, nullable=False)
    points_max: Mapped[float] = mapped_column(Float, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_chunk_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class ResumeRecommendation(Base):
    __tablename__ = "resume_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("resume_evaluations.id"), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(String(20), default="BOTH", nullable=False)


class ResumeAgentRun(Base):
    __tablename__ = "resume_agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), nullable=False, index=True)
    evaluation_id: Mapped[str | None] = mapped_column(ForeignKey("resume_evaluations.id"), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(Enum(AgentRunStatus, native_enum=False, length=20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    qwen_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    telemetry: Mapped[dict | None] = mapped_column(JSON, nullable=True)
