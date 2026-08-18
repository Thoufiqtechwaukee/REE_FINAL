import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
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
from app.db.models.common import CanonicalSection, new_id, utcnow


class ResumeStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    EXTRACTED = "EXTRACTED"
    INDEXED = "INDEXED"
    SKILLS_IDENTIFIED = "SKILLS_IDENTIFIED"
    WAITING_FOR_SKILL_VERIFICATION = "WAITING_FOR_SKILL_VERIFICATION"
    SKILLS_VERIFIED = "SKILLS_VERIFIED"
    EVALUATING = "EVALUATING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ChunkType(str, enum.Enum):
    SUMMARY = "SUMMARY"
    CONTACT = "CONTACT"
    SKILL_SECTION = "SKILL_SECTION"
    EXPERIENCE_ROLE = "EXPERIENCE_ROLE"
    EXPERIENCE_RESPONSIBILITY = "EXPERIENCE_RESPONSIBILITY"
    EXPERIENCE_TECHNOLOGY = "EXPERIENCE_TECHNOLOGY"
    EXPERIENCE_PROJECT = "EXPERIENCE_PROJECT"
    PROJECT = "PROJECT"
    EDUCATION = "EDUCATION"
    CERTIFICATION = "CERTIFICATION"
    ACHIEVEMENT = "ACHIEVEMENT"
    PUBLICATION = "PUBLICATION"
    OTHER = "OTHER"


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    filename: Mapped[str] = mapped_column(String(400), nullable=False)
    pdf_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[ResumeStatus] = mapped_column(
        Enum(ResumeStatus, native_enum=False, length=40), default=ResumeStatus.UPLOADED, nullable=False
    )
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_stage: Mapped[str | None] = mapped_column(String(60), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class ResumeExtraction(Base):
    __tablename__ = "resume_extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    # List[dict] blocks -- block_id/page_number/block_type/text/sequence/
    # heading_context/bounding_box (spec §7). Kept as JSON rather than a
    # separate normalized table since §48's explicit table list has no
    # standalone "blocks" entity -- ResumeChunk is the normalized retrieval
    # unit built from these blocks.
    blocks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    reading_order: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    extraction_version: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResumeSection(Base):
    __tablename__ = "resume_sections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), nullable=False, index=True)
    canonical_section: Mapped[CanonicalSection] = mapped_column(
        Enum(CanonicalSection, native_enum=False, length=20), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    block_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class ResumeChunk(Base):
    __tablename__ = "resume_chunks"

    chunk_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), nullable=False, index=True)
    chunk_type: Mapped[ChunkType] = mapped_column(Enum(ChunkType, native_enum=False, length=30), nullable=False)
    section: Mapped[CanonicalSection] = mapped_column(Enum(CanonicalSection, native_enum=False, length=20), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role_canonical_id: Mapped[str | None] = mapped_column(ForeignKey("roles.role_id"), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_chunk_id: Mapped[str | None] = mapped_column(ForeignKey("resume_chunks.chunk_id"), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    vector_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    embedding_model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    embedding_dimension: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResumeGap(Base):
    __tablename__ = "resume_gaps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resume_id: Mapped[str] = mapped_column(ForeignKey("resumes.id"), nullable=False, index=True)
    gap_start: Mapped[date] = mapped_column(Date, nullable=False)
    gap_end: Mapped[date] = mapped_column(Date, nullable=False)
    duration_months: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
