"""
Resolves the three versioned index files (spec §20) and rebuilds any of them
from SQL Server (the source of truth) if the file is missing or corrupt
(spec §13). Agents never touch FaissVectorStore or file paths directly --
they go through retrieval/resume_retrieval.py and retrieval/skill_retrieval.py
(spec §14), which use this module internally.
"""
import hashlib
from functools import lru_cache

from app.core.config import get_settings
from app.core.versioning import VECTOR_INDEX_VERSION
from app.vector.faiss_store import FaissVectorStore

_DIMENSION = 768


def vector_id_for(key: str) -> int:
    """Deterministic int64 FAISS id derived from a string primary key
    (chunk_id/skill_id/role_id) -- avoids maintaining a separate
    id-allocation table. Stable across re-runs so re-embedding the same
    chunk always replaces (not duplicates) its vector."""
    digest = hashlib.sha256(key.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, "big", signed=False) & 0x7FFFFFFFFFFFFFFF


def _index_path(name: str):
    settings = get_settings()
    return settings.faiss_dir / f"{name}.{VECTOR_INDEX_VERSION}.index"


@lru_cache
def resume_index() -> FaissVectorStore:
    return FaissVectorStore(_index_path("resume_chunks"), _DIMENSION)


@lru_cache
def skill_index() -> FaissVectorStore:
    return FaissVectorStore(_index_path("skill_catalog"), _DIMENSION)


@lru_cache
def role_index() -> FaissVectorStore:
    return FaissVectorStore(_index_path("role_catalog"), _DIMENSION)


def rebuild_resume_index_from_db(db) -> None:
    from app.db.models.resume import ResumeChunk

    rows = (
        db.query(ResumeChunk.vector_id)
        .filter(ResumeChunk.vector_id.isnot(None))
        .all()
    )
    # vectors themselves are not stored in SQL Server (only the mapping) --
    # a true rebuild after FAISS file loss requires re-embedding. This helper
    # exists to make that explicit rather than pretending stale ids are
    # recoverable without Nomic.
    return [r.vector_id for r in rows]


def rebuild_skill_index_from_db(db) -> list[int]:
    from app.db.models.skill import TechnicalSkill

    rows = db.query(TechnicalSkill.vector_id).filter(TechnicalSkill.vector_id.isnot(None)).all()
    return [r.vector_id for r in rows]


def rebuild_role_index_from_db(db) -> list[int]:
    from app.db.models.role import Role

    rows = db.query(Role.vector_id).filter(Role.vector_id.isnot(None)).all()
    return [r.vector_id for r in rows]


def health_check() -> dict:
    return {
        "resume_chunks": resume_index().health_check(),
        "skill_catalog": skill_index().health_check(),
        "role_catalog": role_index().health_check(),
    }
