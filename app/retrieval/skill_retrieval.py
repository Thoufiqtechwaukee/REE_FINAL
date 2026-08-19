"""
Semantic catalog retrieval (spec §14/§20) -- distinct vector domain from
resume chunks, never mixed. Covers both the Technical Skill Catalog index and
the Role Catalog index (role_matcher.py uses the role-side functions here);
both catalogs are global, not resume-scoped.
"""
from sqlalchemy.orm import Session

from app.db.models.role import Role
from app.db.models.skill import TechnicalSkill
from app.embeddings.nomic_client import embed_batch
from app.vector.index_manager import role_index, skill_index


async def search_skill_candidates(
    db: Session, text: str, top_k: int = 5, min_similarity: float = 0.5
) -> list[tuple[TechnicalSkill, float]]:
    query_vec = (await embed_batch([text]))[0]
    hits = skill_index().search(query_vec, top_k=top_k)
    if not hits:
        return []

    vector_ids = [vid for vid, _ in hits]
    rows = db.query(TechnicalSkill).filter(TechnicalSkill.vector_id.in_(vector_ids)).all()
    by_vector_id = {r.vector_id: r for r in rows}

    results: list[tuple[TechnicalSkill, float]] = []
    for vector_id, score in hits:
        if score < min_similarity:
            continue
        skill = by_vector_id.get(vector_id)
        if skill is not None:
            results.append((skill, score))
    return results


async def search_role_candidates(
    db: Session, text: str, top_k: int = 5, min_similarity: float = 0.5
) -> list[tuple[Role, float]]:
    query_vec = (await embed_batch([text]))[0]
    hits = role_index().search(query_vec, top_k=top_k)
    if not hits:
        return []

    vector_ids = [vid for vid, _ in hits]
    rows = db.query(Role).filter(Role.vector_id.in_(vector_ids)).all()
    by_vector_id = {r.vector_id: r for r in rows}

    results: list[tuple[Role, float]] = []
    for vector_id, score in hits:
        if score < min_similarity:
            continue
        role = by_vector_id.get(vector_id)
        if role is not None:
            results.append((role, score))
    return results
