"""Technical Skill Catalog (spec §16-21) -- authoritative source of skill
identity. Nothing outside admin/seed tooling writes new rows here at runtime;
the discovery/verification pipeline only ever selects among existing rows."""
import enum
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.common import utcnow


class SkillAliasType(str, enum.Enum):
    ALIAS = "ALIAS"
    ABBREVIATION = "ABBREVIATION"
    MISSPELLING = "MISSPELLING"


class TechnicalSkillCategory(Base):
    __tablename__ = "technical_skill_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    skills: Mapped[list["TechnicalSkill"]] = relationship(back_populates="category")


class TechnicalSkill(Base):
    __tablename__ = "technical_skills"

    skill_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(150), nullable=False)
    skill_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("technical_skill_categories.id"), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parent_skill_id: Mapped[str | None] = mapped_column(ForeignKey("technical_skills.skill_id"), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[str] = mapped_column(String(30), default="skill-taxonomy-v1", nullable=False)
    vector_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    category: Mapped["TechnicalSkillCategory | None"] = relationship(back_populates="skills")
    aliases: Mapped[list["TechnicalSkillAlias"]] = relationship(
        back_populates="skill", cascade="all, delete-orphan"
    )


class TechnicalSkillAlias(Base):
    __tablename__ = "technical_skill_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("technical_skills.skill_id"), nullable=False, index=True)
    alias_text: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    alias_type: Mapped[SkillAliasType] = mapped_column(
        Enum(SkillAliasType, native_enum=False, length=20), default=SkillAliasType.ALIAS, nullable=False
    )

    skill: Mapped["TechnicalSkill"] = relationship(back_populates="aliases")


class TechnicalSkillRelation(Base):
    __tablename__ = "technical_skill_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("technical_skills.skill_id"), nullable=False, index=True)
    related_skill_id: Mapped[str] = mapped_column(ForeignKey("technical_skills.skill_id"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(30), default="RELATED", nullable=False)
