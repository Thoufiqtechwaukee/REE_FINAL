"""
Idempotent loader for the Technical Skill Catalog and Role Catalog seed data
(spec §61/§62 -- "Build this as seed data/migrations, NOT hard-coded Python
lists scattered through application code"). Safe to re-run: every entity is
looked up by its stable id/name first and updated in place rather than
duplicated, so re-running after editing a seed JSON file converges the DB to
match the file.

Usage:  .venv/Scripts/python.exe scripts/seed_taxonomy.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.models.role import Role, RoleAlias, RoleDomain, RoleLevel, RoleSkillRelation
from app.db.models.skill import (
    TechnicalSkill,
    TechnicalSkillAlias,
    TechnicalSkillCategory,
    TechnicalSkillRelation,
)
from app.db.session import SessionLocal

_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _ROOT / "app" / "taxonomy" / "skills"
_ROLES_DIR = _ROOT / "app" / "taxonomy" / "roles"


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seed_role_levels(db):
    for row in _load(_ROLES_DIR / "seed_role_levels.json"):
        level = db.get(RoleLevel, row["id"])
        if level is None:
            level = RoleLevel(id=row["id"])
            db.add(level)
        level.name = row["name"]
        level.rank = row["rank"]
    db.commit()
    print(f"RoleLevel: {db.query(RoleLevel).count()} rows")


def seed_role_domains(db) -> dict[str, int]:
    name_to_id: dict[str, int] = {}
    for name in _load(_ROLES_DIR / "seed_role_domains.json"):
        domain = db.query(RoleDomain).filter(RoleDomain.name == name).one_or_none()
        if domain is None:
            domain = RoleDomain(name=name)
            db.add(domain)
            db.flush()
        name_to_id[name] = domain.id
    db.commit()
    print(f"RoleDomain: {db.query(RoleDomain).count()} rows")
    return name_to_id


def seed_skill_categories(db) -> dict[str, int]:
    name_to_id: dict[str, int] = {}
    for name in _load(_SKILLS_DIR / "seed_skill_categories.json"):
        cat = db.query(TechnicalSkillCategory).filter(TechnicalSkillCategory.name == name).one_or_none()
        if cat is None:
            cat = TechnicalSkillCategory(name=name)
            db.add(cat)
            db.flush()
        name_to_id[name] = cat.id
    db.commit()
    print(f"TechnicalSkillCategory: {db.query(TechnicalSkillCategory).count()} rows")
    return name_to_id


def seed_skills(db, category_ids: dict[str, int]):
    rows = _load(_SKILLS_DIR / "seed_skills.json")
    seen_ids = set()

    # Pass 1: upsert every skill row without parent_skill_id (avoids
    # self-referential FK ordering issues on first insert).
    for row in rows:
        skill_id = row["skill_id"]
        seen_ids.add(skill_id)
        skill = db.get(TechnicalSkill, skill_id)
        if skill is None:
            skill = TechnicalSkill(skill_id=skill_id)
            db.add(skill)
        skill.canonical_name = row["canonical_name"]
        skill.display_name = row.get("display_name", row["canonical_name"])
        skill.skill_type = row["skill_type"]
        skill.category_id = category_ids.get(row.get("category"))
        skill.subcategory = row.get("subcategory")
        skill.description = row.get("description")
        skill.deprecated = row.get("deprecated", False)
        skill.active = row.get("active", True)
        skill.parent_skill_id = None
    db.commit()

    unknown_parents = []
    for row in rows:
        parent_id = row.get("parent_skill_id")
        if parent_id:
            if parent_id not in seen_ids:
                unknown_parents.append((row["skill_id"], parent_id))
                continue
            db.get(TechnicalSkill, row["skill_id"]).parent_skill_id = parent_id
    db.commit()
    if unknown_parents:
        print(f"  WARNING unknown parent_skill_id refs skipped: {unknown_parents}")

    # Aliases: clear and re-add per skill for idempotency.
    for row in rows:
        skill_id = row["skill_id"]
        db.query(TechnicalSkillAlias).filter(TechnicalSkillAlias.skill_id == skill_id).delete()
        for alias in row.get("aliases", []):
            db.add(TechnicalSkillAlias(skill_id=skill_id, alias_text=alias, alias_type="ALIAS"))
        for abbr in row.get("abbreviations", []):
            db.add(TechnicalSkillAlias(skill_id=skill_id, alias_text=abbr, alias_type="ABBREVIATION"))
        for misspelling in row.get("common_misspellings", []):
            db.add(TechnicalSkillAlias(skill_id=skill_id, alias_text=misspelling, alias_type="MISSPELLING"))
    db.commit()

    # Relations: clear and re-add per skill.
    unknown_related = []
    for row in rows:
        skill_id = row["skill_id"]
        db.query(TechnicalSkillRelation).filter(TechnicalSkillRelation.skill_id == skill_id).delete()
        for related_id in row.get("related_skill_ids", []):
            if related_id not in seen_ids:
                unknown_related.append((skill_id, related_id))
                continue
            db.add(TechnicalSkillRelation(skill_id=skill_id, related_skill_id=related_id, relation_type="RELATED"))
    db.commit()
    if unknown_related:
        print(f"  WARNING unknown related_skill_id refs skipped: {unknown_related}")

    print(f"TechnicalSkill: {db.query(TechnicalSkill).count()} rows")
    print(f"TechnicalSkillAlias: {db.query(TechnicalSkillAlias).count()} rows")
    print(f"TechnicalSkillRelation: {db.query(TechnicalSkillRelation).count()} rows")


def seed_roles(db, domain_ids: dict[str, int]):
    rows = _load(_ROLES_DIR / "seed_roles.json")
    level_by_name = {lvl.name: lvl.id for lvl in db.query(RoleLevel).all()}
    all_skill_ids = {s.skill_id for s in db.query(TechnicalSkill.skill_id).all()}

    seen_ids = set()
    for row in rows:
        role_id = row["role_id"]
        seen_ids.add(role_id)
        role = db.get(Role, role_id)
        if role is None:
            role = Role(role_id=role_id)
            db.add(role)
        role.canonical_title = row["canonical_title"]
        role.normalized_title = row["canonical_title"].strip().lower()
        role.role_family = row["role_family"]
        role.domain_id = domain_ids.get(row.get("domain"))
        level_name = row.get("seniority_level")
        role.seniority_level_id = level_by_name.get(level_name) if level_name else None
        role.description = row.get("description")
        role.active = row.get("active", True)
    db.commit()

    unknown_related = []
    for row in rows:
        role_id = row["role_id"]
        db.query(RoleAlias).filter(RoleAlias.role_id == role_id).delete()
        for alias in row.get("aliases", []):
            db.add(RoleAlias(role_id=role_id, alias_text=alias))

        db.query(RoleSkillRelation).filter(RoleSkillRelation.role_id == role_id).delete()
        for skill_id in row.get("related_skill_ids", []):
            if skill_id not in all_skill_ids:
                unknown_related.append((role_id, skill_id))
                continue
            db.add(RoleSkillRelation(role_id=role_id, skill_id=skill_id, relation_type="RELATED"))
    db.commit()
    if unknown_related:
        print(f"  WARNING unknown related_skill_id refs skipped: {unknown_related}")

    print(f"Role: {db.query(Role).count()} rows")
    print(f"RoleAlias: {db.query(RoleAlias).count()} rows")
    print(f"RoleSkillRelation: {db.query(RoleSkillRelation).count()} rows")


def main():
    db = SessionLocal()
    try:
        seed_role_levels(db)
        domain_ids = seed_role_domains(db)
        category_ids = seed_skill_categories(db)
        seed_skills(db, category_ids)
        seed_roles(db, domain_ids)
    finally:
        db.close()


if __name__ == "__main__":
    main()
