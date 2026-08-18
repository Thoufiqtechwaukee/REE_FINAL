"""
Generates and indexes embeddings for the Technical Skill Catalog and Role
Catalog (spec §20's second vector domain -- distinct from resume chunks).
Idempotent: re-running re-embeds and re-adds every row (add_vectors replaces
by id, never duplicates).

Usage:  .venv/Scripts/python.exe scripts/embed_catalogs.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models.role import Role
from app.db.models.skill import TechnicalSkill
from app.db.session import SessionLocal
from app.embeddings.nomic_client import embed_batch
from app.vector.index_manager import role_index, skill_index, vector_id_for


async def embed_skills(db):
    skills = db.query(TechnicalSkill).filter(TechnicalSkill.active == True).all()
    if not skills:
        return
    texts = [
        f"{s.canonical_name}. Category: {s.category.name if s.category else ''}. {s.description or ''}".strip()
        for s in skills
    ]
    vectors = await embed_batch(texts)
    ids = []
    for s in skills:
        s.vector_id = vector_id_for(s.skill_id)
        ids.append(s.vector_id)
    db.commit()
    skill_index().add_vectors(ids, vectors)
    print(f"Embedded and indexed {len(skills)} skills.")


async def embed_roles(db):
    roles = db.query(Role).filter(Role.active == True).all()
    if not roles:
        return
    texts = [
        f"{r.canonical_title}. Family: {r.role_family}. {r.description or ''}".strip()
        for r in roles
    ]
    vectors = await embed_batch(texts)
    ids = []
    for r in roles:
        r.vector_id = vector_id_for(r.role_id)
        ids.append(r.vector_id)
    db.commit()
    role_index().add_vectors(ids, vectors)
    print(f"Embedded and indexed {len(roles)} roles.")


async def main():
    db = SessionLocal()
    try:
        await embed_skills(db)
        await embed_roles(db)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
