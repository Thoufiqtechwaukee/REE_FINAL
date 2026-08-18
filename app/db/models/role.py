"""Role Catalog (spec §24-29) -- authoritative source of professional role
identity, separate from technical skill identity."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.common import utcnow


class RoleDomain(Base):
    __tablename__ = "role_domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class RoleLevel(Base):
    """The 16-level seniority ladder from spec §28. Fixed ids 1-16, seeded once."""

    __tablename__ = "role_levels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)


class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    canonical_title: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, index=True)
    normalized_title: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    role_family: Mapped[str] = mapped_column(String(100), nullable=False)
    domain_id: Mapped[int | None] = mapped_column(ForeignKey("role_domains.id"), nullable=True)
    seniority_level_id: Mapped[int | None] = mapped_column(ForeignKey("role_levels.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[str] = mapped_column(String(30), default="role-taxonomy-v1", nullable=False)
    vector_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    domain: Mapped["RoleDomain | None"] = relationship()
    seniority_level: Mapped["RoleLevel | None"] = relationship()
    aliases: Mapped[list["RoleAlias"]] = relationship(back_populates="role", cascade="all, delete-orphan")


class RoleAlias(Base):
    __tablename__ = "role_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.role_id"), nullable=False, index=True)
    alias_text: Mapped[str] = mapped_column(String(150), nullable=False, index=True)

    role: Mapped["Role"] = relationship(back_populates="aliases")


class RoleSkillRelation(Base):
    """RELATED (never MANDATORY) skills commonly associated with a role --
    used for context/retrieval/growth reasoning only, never for scoring
    penalties (spec §54/§55)."""

    __tablename__ = "role_skill_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.role_id"), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("technical_skills.skill_id"), nullable=False, index=True)
    relation_type: Mapped[str] = mapped_column(String(30), default="RELATED", nullable=False)
