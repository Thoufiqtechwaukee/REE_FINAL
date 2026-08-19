"""
ResumeRetrievalService (spec §15). Every operation takes resume_id and never
returns another resume's chunks -- enforced structurally, not by convention:
the FAISS search's allowed_ids set is always derived from a SQL Server query
already filtered to that resume_id, so a bug in a caller's query text can
never leak cross-resume results (spec §53). Agents call only this module and
skill_retrieval.py -- they never touch FaissVectorStore/index paths/vector
dimensions directly (spec §14).
"""
from sqlalchemy.orm import Session

from app.db.models.resume import ResumeChunk
from app.embeddings.nomic_client import embed_batch
from app.models.retrieval import RetrievalFilter, RetrievalResult
from app.vector.index_manager import resume_index


def _resume_scoped_query(db: Session, resume_id: str, filters: RetrievalFilter | None):
    q = db.query(ResumeChunk).filter(ResumeChunk.resume_id == resume_id, ResumeChunk.vector_id.isnot(None))
    if filters:
        if filters.section:
            q = q.filter(ResumeChunk.section == filters.section)
        if filters.chunk_type:
            q = q.filter(ResumeChunk.chunk_type == filters.chunk_type)
        if filters.company:
            q = q.filter(ResumeChunk.company == filters.company)
        if filters.role_canonical_id:
            q = q.filter(ResumeChunk.role_canonical_id == filters.role_canonical_id)
        if filters.date_from:
            q = q.filter((ResumeChunk.end_date.is_(None)) | (ResumeChunk.end_date >= filters.date_from))
        if filters.date_to:
            q = q.filter((ResumeChunk.start_date.is_(None)) | (ResumeChunk.start_date <= filters.date_to))
    return q


async def search_resume(
    db: Session,
    resume_id: str,
    query_text: str,
    top_k: int = 5,
    filters: RetrievalFilter | None = None,
    min_similarity: float = 0.0,
) -> list[RetrievalResult]:
    scoped_rows = _resume_scoped_query(db, resume_id, filters).all()
    if not scoped_rows:
        return []
    vector_id_to_chunk = {row.vector_id: row for row in scoped_rows}

    query_vec = (await embed_batch([query_text]))[0]
    hits = resume_index().search(query_vec, top_k=top_k, allowed_ids=set(vector_id_to_chunk.keys()))

    results: list[RetrievalResult] = []
    for vector_id, score in hits:
        if score < min_similarity:
            continue
        chunk = vector_id_to_chunk[vector_id]
        results.append(
            RetrievalResult(
                chunk_id=chunk.chunk_id,
                resume_id=chunk.resume_id,
                score=score,
                chunk_type=chunk.chunk_type.value if hasattr(chunk.chunk_type, "value") else chunk.chunk_type,
                section=chunk.section.value if hasattr(chunk.section, "value") else chunk.section,
                company=chunk.company,
                role_raw=chunk.role_raw,
                role_canonical_id=chunk.role_canonical_id,
                page_number=chunk.page_number,
                original_text=chunk.original_text,
                start_date=chunk.start_date,
                end_date=chunk.end_date,
            )
        )
    return results


async def search_skill_evidence(db: Session, resume_id: str, skill_name: str, top_k: int = 5) -> list[RetrievalResult]:
    query = f"Find professional evidence demonstrating implementation or use of {skill_name}."
    return await search_resume(db, resume_id, query, top_k=top_k, min_similarity=0.3)


async def search_experience(db: Session, resume_id: str, top_k: int = 10) -> list[RetrievalResult]:
    query = "Find the most recent responsibilities and technical environment of the candidate."
    return await search_resume(
        db, resume_id, query, top_k=top_k, filters=RetrievalFilter(section="EXPERIENCE")
    )


async def search_growth_evidence(db: Session, resume_id: str, top_k: int = 10) -> list[RetrievalResult]:
    query = (
        "Find evidence of increasing ownership, technical complexity, leadership, scope, "
        "architecture responsibility or stakeholder responsibility across the candidate's career."
    )
    return await search_resume(db, resume_id, query, top_k=top_k)


async def search_section(db: Session, resume_id: str, section: str, top_k: int = 20) -> list[RetrievalResult]:
    return await search_resume(
        db, resume_id, f"Find content from the {section} section.", top_k=top_k, filters=RetrievalFilter(section=section)
    )


async def search_project_evidence(db: Session, resume_id: str, top_k: int = 10) -> list[RetrievalResult]:
    query = "Find project work demonstrating hands-on technical implementation."
    return await search_resume(
        db, resume_id, query, top_k=top_k, filters=RetrievalFilter(chunk_type="PROJECT")
    )
