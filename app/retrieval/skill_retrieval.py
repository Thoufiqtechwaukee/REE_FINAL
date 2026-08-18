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


async def search_skill_candidates_batch(
    db: Session, texts: list[str], top_k: int = 5, min_similarity: float = 0.5
) -> dict[str, list[tuple[TechnicalSkill, float]]]:
    """Batched counterpart to search_skill_candidates -- one embedding
    round-trip for every text instead of one per text. FAISS search and the
    catalog lookup still run per text/across all texts respectively, but both
    are local (no network I/O), so batching them changes nothing except
    avoiding one SQL round-trip per text -- results are identical to calling
    search_skill_candidates once per text. Returns a dict keyed by the
    original text (duplicates collapse to one entry)."""
    if not texts:
        return {}
    unique_texts = list(dict.fromkeys(texts))
    query_vecs = await embed_batch(unique_texts)

    per_text_hits: dict[str, list[tuple[int, float]]] = {}
    all_vector_ids: set[int] = set()
    for text, vec in zip(unique_texts, query_vecs):
        hits = skill_index().search(vec, top_k=top_k)
        per_text_hits[text] = hits
        all_vector_ids.update(vid for vid, _ in hits)

    by_vector_id: dict[int, TechnicalSkill] = {}
    if all_vector_ids:
        rows = db.query(TechnicalSkill).filter(TechnicalSkill.vector_id.in_(all_vector_ids)).all()
        by_vector_id = {r.vector_id: r for r in rows}

    results: dict[str, list[tuple[TechnicalSkill, float]]] = {}
    for text in unique_texts:
        text_results = []
        for vector_id, score in per_text_hits.get(text, []):
            if score < min_similarity:
                continue
            skill = by_vector_id.get(vector_id)
            if skill is not None:
                text_results.append((skill, score))
        results[text] = text_results
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


async def search_role_candidates_batch(
    db: Session, texts: list[str], top_k: int = 5, min_similarity: float = 0.5
) -> dict[str, list[tuple[Role, float]]]:
    """Batched counterpart to search_role_candidates -- the role-side twin of
    search_skill_candidates_batch, with identical semantics: one embedding
    round-trip for every text instead of one per text, while FAISS search
    stays per-text (local, no network I/O) and the catalog lookup collapses to
    a single SQL query across all hits. Per-text top_k/min_similarity, and
    therefore results, are identical to calling search_role_candidates once
    per text -- a performance change only. Returns a dict keyed by the
    original text (duplicates collapse to one entry)."""
    if not texts:
        return {}
    unique_texts = list(dict.fromkeys(texts))
    query_vecs = await embed_batch(unique_texts)

    per_text_hits: dict[str, list[tuple[int, float]]] = {}
    all_vector_ids: set[int] = set()
    for text, vec in zip(unique_texts, query_vecs):
        hits = role_index().search(vec, top_k=top_k)
        per_text_hits[text] = hits
        all_vector_ids.update(vid for vid, _ in hits)

    by_vector_id: dict[int, Role] = {}
    if all_vector_ids:
        rows = db.query(Role).filter(Role.vector_id.in_(all_vector_ids)).all()
        by_vector_id = {r.vector_id: r for r in rows}

    results: dict[str, list[tuple[Role, float]]] = {}
    for text in unique_texts:
        text_results = []
        for vector_id, score in per_text_hits.get(text, []):
            if score < min_similarity:
                continue
            role = by_vector_id.get(vector_id)
            if role is not None:
                text_results.append((role, score))
        results[text] = text_results
    return results
