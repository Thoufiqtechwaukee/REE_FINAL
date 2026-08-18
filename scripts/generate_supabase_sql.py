"""
Generator for supabase_schema.sql:
Creates a clean, robust, standalone SQL script for Supabase SQL Editor.
- Enables pgvector extension (CREATE EXTENSION IF NOT EXISTS vector;)
- Creates all 21 PostgreSQL tables matching exact SQLAlchemy ORM models
- Adds embedding vector(768) columns for RAG support
- Formats and generates SQL INSERT statements for:
  * 16 Role Levels
  * Role Domains
  * Technical Skill Categories
  * 440 Technical Skills + Aliases + Relations
  * 220 Roles + Aliases + Relations
"""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SKILLS_DIR = _ROOT / "app" / "taxonomy" / "skills"
_ROLES_DIR = _ROOT / "app" / "taxonomy" / "roles"
_OUTPUT_FILE = _ROOT / "supabase_schema.sql"


def esc(val):
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (list, dict)):
        s = json.dumps(val).replace("'", "''")
        return f"'{s}'::jsonb"
    s = str(val).replace("'", "''")
    return f"'{s}'"


def generate_sql():
    sql = []
    sql.append("-- ========================================================")
    sql.append("-- REE FINAL: Supabase PostgreSQL Schema & Complete Seed Data")
    sql.append("-- Matches exact SQLAlchemy ORM models and enables pgvector RAG")
    sql.append("-- ========================================================\n")
    sql.append("CREATE EXTENSION IF NOT EXISTS vector;\n")

    # DDL matching SQLAlchemy ORM models in app/db/models/
    sql.append("""
-- 1. Role Levels
CREATE TABLE IF NOT EXISTS role_levels (
    id INT PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    rank INT UNIQUE NOT NULL
);

-- 2. Role Domains
CREATE TABLE IF NOT EXISTS role_domains (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT
);

-- 3. Technical Skill Categories
CREATE TABLE IF NOT EXISTS technical_skill_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT
);

-- 4. Technical Skills
CREATE TABLE IF NOT EXISTS technical_skills (
    skill_id VARCHAR(80) PRIMARY KEY,
    canonical_name VARCHAR(150) UNIQUE NOT NULL,
    display_name VARCHAR(150) NOT NULL,
    skill_type VARCHAR(50) NOT NULL,
    category_id INT REFERENCES technical_skill_categories(id) ON DELETE SET NULL,
    subcategory VARCHAR(100),
    parent_skill_id VARCHAR(80) REFERENCES technical_skills(skill_id) ON DELETE SET NULL,
    description TEXT,
    deprecated BOOLEAN DEFAULT FALSE NOT NULL,
    active BOOLEAN DEFAULT TRUE NOT NULL,
    version VARCHAR(30) DEFAULT 'skill-taxonomy-v1' NOT NULL,
    vector_id BIGINT,
    embedding vector(768),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 5. Technical Skill Aliases
CREATE TABLE IF NOT EXISTS technical_skill_aliases (
    id SERIAL PRIMARY KEY,
    skill_id VARCHAR(80) NOT NULL REFERENCES technical_skills(skill_id) ON DELETE CASCADE,
    alias_text VARCHAR(150) NOT NULL,
    alias_type VARCHAR(20) DEFAULT 'ALIAS' NOT NULL
);

-- 6. Technical Skill Relations
CREATE TABLE IF NOT EXISTS technical_skill_relations (
    id SERIAL PRIMARY KEY,
    skill_id VARCHAR(80) NOT NULL REFERENCES technical_skills(skill_id) ON DELETE CASCADE,
    related_skill_id VARCHAR(80) NOT NULL REFERENCES technical_skills(skill_id) ON DELETE CASCADE,
    relation_type VARCHAR(30) DEFAULT 'RELATED' NOT NULL
);

-- 7. Roles
CREATE TABLE IF NOT EXISTS roles (
    role_id VARCHAR(100) PRIMARY KEY,
    canonical_title VARCHAR(150) UNIQUE NOT NULL,
    normalized_title VARCHAR(150) NOT NULL,
    role_family VARCHAR(100) NOT NULL,
    domain_id INT REFERENCES role_domains(id) ON DELETE SET NULL,
    seniority_level_id INT REFERENCES role_levels(id) ON DELETE SET NULL,
    description TEXT,
    active BOOLEAN DEFAULT TRUE NOT NULL,
    version VARCHAR(30) DEFAULT 'role-taxonomy-v1' NOT NULL,
    vector_id BIGINT,
    embedding vector(768),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 8. Role Aliases
CREATE TABLE IF NOT EXISTS role_aliases (
    id SERIAL PRIMARY KEY,
    role_id VARCHAR(100) NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    alias_text VARCHAR(150) NOT NULL
);

-- 9. Role Skill Relations
CREATE TABLE IF NOT EXISTS role_skill_relations (
    id SERIAL PRIMARY KEY,
    role_id VARCHAR(100) NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    skill_id VARCHAR(80) NOT NULL REFERENCES technical_skills(skill_id) ON DELETE CASCADE,
    relation_type VARCHAR(30) DEFAULT 'RELATED' NOT NULL
);

-- 10. Resumes (Matching app/db/models/resume.py)
CREATE TABLE IF NOT EXISTS resumes (
    id VARCHAR(36) PRIMARY KEY,
    filename VARCHAR(400) NOT NULL,
    pdf_hash VARCHAR(64) NOT NULL,
    storage_path VARCHAR(500) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'UPLOADED',
    page_count INT DEFAULT 0 NOT NULL,
    failed_stage VARCHAR(60),
    failure_reason TEXT,
    uploaded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 11. Resume Extractions
CREATE TABLE IF NOT EXISTS resume_extractions (
    id SERIAL PRIMARY KEY,
    resume_id VARCHAR(36) NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
    reading_order JSONB NOT NULL DEFAULT '[]'::jsonb,
    extraction_version VARCHAR(30) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 12. Resume Sections
CREATE TABLE IF NOT EXISTS resume_sections (
    id SERIAL PRIMARY KEY,
    resume_id VARCHAR(36) NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    canonical_section VARCHAR(20) NOT NULL,
    confidence FLOAT NOT NULL,
    page_number INT NOT NULL,
    sequence INT NOT NULL,
    block_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    text TEXT NOT NULL
);

-- 13. Resume Chunks
CREATE TABLE IF NOT EXISTS resume_chunks (
    chunk_id VARCHAR(36) PRIMARY KEY,
    resume_id VARCHAR(36) NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    chunk_type VARCHAR(30) NOT NULL,
    section VARCHAR(20) NOT NULL,
    company VARCHAR(200),
    role_raw VARCHAR(200),
    role_canonical_id VARCHAR(100) REFERENCES roles(role_id) ON DELETE SET NULL,
    start_date DATE,
    end_date DATE,
    is_current BOOLEAN DEFAULT FALSE NOT NULL,
    page_number INT NOT NULL,
    parent_chunk_id VARCHAR(36) REFERENCES resume_chunks(chunk_id),
    sequence INT NOT NULL,
    original_text TEXT NOT NULL,
    embedding_text TEXT NOT NULL,
    vector_id BIGINT,
    embedding_model VARCHAR(60),
    embedding_version VARCHAR(30),
    embedding_dimension INT,
    embedding vector(768),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 14. Resume Gaps
CREATE TABLE IF NOT EXISTS resume_gaps (
    id SERIAL PRIMARY KEY,
    resume_id VARCHAR(36) NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    gap_start DATE NOT NULL,
    gap_end DATE NOT NULL,
    duration_months INT NOT NULL,
    explanation TEXT,
    confidence FLOAT
);

-- 15. Resume Skills (Verification Gate)
CREATE TABLE IF NOT EXISTS resume_skills (
    id VARCHAR(36) PRIMARY KEY,
    resume_id VARCHAR(36) NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    skill_id VARCHAR(80) NOT NULL REFERENCES technical_skills(skill_id) ON DELETE CASCADE,
    detected_text VARCHAR(150) NOT NULL,
    detection_method VARCHAR(30) NOT NULL,
    confidence FLOAT NOT NULL,
    verification_status VARCHAR(30) DEFAULT 'AUTO_CONFIRMED' NOT NULL,
    user_modified BOOLEAN DEFAULT FALSE NOT NULL,
    source_chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 16. Resume Experiences
CREATE TABLE IF NOT EXISTS resume_experiences (
    id VARCHAR(36) PRIMARY KEY,
    resume_id VARCHAR(36) NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    company VARCHAR(200) NOT NULL,
    raw_title VARCHAR(200) NOT NULL,
    canonical_role_id VARCHAR(100) REFERENCES roles(role_id) ON DELETE SET NULL,
    canonical_title VARCHAR(200),
    role_family VARCHAR(100),
    seniority_level_id INT REFERENCES role_levels(id) ON DELETE SET NULL,
    seniority_ambiguous BOOLEAN DEFAULT FALSE NOT NULL,
    start_date DATE,
    end_date DATE,
    is_current BOOLEAN DEFAULT FALSE NOT NULL,
    duration_months INT DEFAULT 0 NOT NULL,
    responsibilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    technologies JSONB NOT NULL DEFAULT '[]'::jsonb,
    projects JSONB NOT NULL DEFAULT '[]'::jsonb,
    leadership_indicators JSONB NOT NULL DEFAULT '[]'::jsonb,
    ownership_indicators JSONB NOT NULL DEFAULT '[]'::jsonb,
    responsibility_level VARCHAR(40),
    source_chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence FLOAT DEFAULT 1.0 NOT NULL,
    sequence INT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 17. Resume Evaluations
CREATE TABLE IF NOT EXISTS resume_evaluations (
    id VARCHAR(36) PRIMARY KEY,
    resume_id VARCHAR(36) NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    target_role_raw VARCHAR(200) NOT NULL,
    target_role_canonical_id VARCHAR(100) REFERENCES roles(role_id) ON DELETE SET NULL,
    matched_role_id VARCHAR(100) REFERENCES roles(role_id) ON DELETE SET NULL,
    role_domain_id INT REFERENCES role_domains(id) ON DELETE SET NULL,
    overall_score FLOAT DEFAULT 0.0 NOT NULL,
    tier VARCHAR(30),
    completeness_score FLOAT DEFAULT 0.0 NOT NULL,
    growth_score FLOAT DEFAULT 0.0 NOT NULL,
    evidence_score FLOAT DEFAULT 0.0 NOT NULL,
    experience_score FLOAT DEFAULT 0.0 NOT NULL,
    summary TEXT,
    status VARCHAR(30) DEFAULT 'COMPLETED' NOT NULL,
    evaluation_version VARCHAR(30) DEFAULT 'eval-v1' NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 18. Resume Evaluation Scores
CREATE TABLE IF NOT EXISTS resume_evaluation_scores (
    id SERIAL PRIMARY KEY,
    evaluation_id VARCHAR(36) NOT NULL REFERENCES resume_evaluations(id) ON DELETE CASCADE,
    category VARCHAR(30) NOT NULL,
    aspect_key VARCHAR(60) NOT NULL,
    score FLOAT NOT NULL,
    max_score FLOAT NOT NULL,
    weight FLOAT NOT NULL,
    reasoning TEXT NOT NULL,
    evidence_chunk_ids JSONB NOT NULL DEFAULT '[]'::jsonb
);

-- 19. Resume Skill Evidence
CREATE TABLE IF NOT EXISTS resume_skill_evidence (
    id SERIAL PRIMARY KEY,
    evaluation_id VARCHAR(36) NOT NULL REFERENCES resume_evaluations(id) ON DELETE CASCADE,
    skill_id VARCHAR(80) NOT NULL REFERENCES technical_skills(skill_id) ON DELETE CASCADE,
    evidence_type VARCHAR(40) NOT NULL,
    strength VARCHAR(20) NOT NULL,
    chunk_id VARCHAR(36) REFERENCES resume_chunks(chunk_id) ON DELETE SET NULL,
    snippet TEXT,
    reasoning TEXT NOT NULL
);

-- 20. Resume Recommendations
CREATE TABLE IF NOT EXISTS resume_recommendations (
    id SERIAL PRIMARY KEY,
    evaluation_id VARCHAR(36) NOT NULL REFERENCES resume_evaluations(id) ON DELETE CASCADE,
    category VARCHAR(40) NOT NULL,
    title VARCHAR(150) NOT NULL,
    description TEXT NOT NULL,
    target_skill_id VARCHAR(80) REFERENCES technical_skills(skill_id) ON DELETE SET NULL,
    priority VARCHAR(20) DEFAULT 'MEDIUM' NOT NULL
);

-- 21. Resume Agent Runs
CREATE TABLE IF NOT EXISTS resume_agent_runs (
    id SERIAL PRIMARY KEY,
    evaluation_id VARCHAR(36) NOT NULL REFERENCES resume_evaluations(id) ON DELETE CASCADE,
    agent_name VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    duration_ms INT NOT NULL,
    prompt_tokens INT,
    completion_tokens INT,
    model_name VARCHAR(60),
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP NOT NULL
);

""")

    # Seed Role Levels
    sql.append("-- ========================================================")
    sql.append("-- SEED DATA: Role Levels")
    sql.append("-- ========================================================")
    with open(_ROLES_DIR / "seed_role_levels.json", encoding="utf-8") as f:
        levels = json.load(f)
    for lvl in levels:
        sql.append(f"INSERT INTO role_levels (id, name, rank) VALUES ({lvl['id']}, {esc(lvl['name'])}, {lvl['rank']}) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, rank = EXCLUDED.rank;")
    sql.append("")

    # Seed Role Domains
    sql.append("-- ========================================================")
    sql.append("-- SEED DATA: Role Domains")
    sql.append("-- ========================================================")
    with open(_ROLES_DIR / "seed_role_domains.json", encoding="utf-8") as f:
        domains = json.load(f)
    domain_map = {}
    for idx, dname in enumerate(domains, 1):
        domain_map[dname] = idx
        sql.append(f"INSERT INTO role_domains (id, name) VALUES ({idx}, {esc(dname)}) ON CONFLICT (name) DO NOTHING;")
    sql.append("")

    # Seed Skill Categories
    sql.append("-- ========================================================")
    sql.append("-- SEED DATA: Technical Skill Categories")
    sql.append("-- ========================================================")
    with open(_SKILLS_DIR / "seed_skill_categories.json", encoding="utf-8") as f:
        categories = json.load(f)
    category_map = {}
    for idx, cname in enumerate(categories, 1):
        category_map[cname] = idx
        sql.append(f"INSERT INTO technical_skill_categories (id, name) VALUES ({idx}, {esc(cname)}) ON CONFLICT (name) DO NOTHING;")
    sql.append("")

    # Seed Technical Skills
    sql.append("-- ========================================================")
    sql.append("-- SEED DATA: Technical Skills (440 entries)")
    sql.append("-- ========================================================")
    with open(_SKILLS_DIR / "seed_skills.json", encoding="utf-8") as f:
        skills = json.load(f)

    skill_ids_set = {s["skill_id"] for s in skills}

    # Pass 1: Base skills without parent FK
    for s in skills:
        cat_id = category_map.get(s.get("category"))
        cat_val = esc(cat_id)
        sql.append(
            f"INSERT INTO technical_skills (skill_id, canonical_name, display_name, skill_type, category_id, subcategory, description, deprecated, active) "
            f"VALUES ({esc(s['skill_id'])}, {esc(s['canonical_name'])}, {esc(s.get('display_name', s['canonical_name']))}, {esc(s['skill_type'])}, {cat_val}, {esc(s.get('subcategory'))}, {esc(s.get('description'))}, {esc(s.get('deprecated', False))}, {esc(s.get('active', True))}) "
            f"ON CONFLICT (skill_id) DO UPDATE SET canonical_name = EXCLUDED.canonical_name, display_name = EXCLUDED.display_name, skill_type = EXCLUDED.skill_type, category_id = EXCLUDED.category_id, subcategory = EXCLUDED.subcategory, description = EXCLUDED.description;"
        )

    # Pass 2: Parent skill updates
    sql.append("\n-- Skill Parent References")
    for s in skills:
        parent_id = s.get("parent_skill_id")
        if parent_id and parent_id in skill_ids_set:
            sql.append(f"UPDATE technical_skills SET parent_skill_id = {esc(parent_id)} WHERE skill_id = {esc(s['skill_id'])};")

    # Pass 3: Aliases
    sql.append("\n-- Technical Skill Aliases")
    for s in skills:
        sid = s["skill_id"]
        for alias in s.get("aliases", []):
            sql.append(f"INSERT INTO technical_skill_aliases (skill_id, alias_text, alias_type) VALUES ({esc(sid)}, {esc(alias)}, 'ALIAS');")
        for abbr in s.get("abbreviations", []):
            sql.append(f"INSERT INTO technical_skill_aliases (skill_id, alias_text, alias_type) VALUES ({esc(sid)}, {esc(abbr)}, 'ABBREVIATION');")
        for misspelling in s.get("common_misspellings", []):
            sql.append(f"INSERT INTO technical_skill_aliases (skill_id, alias_text, alias_type) VALUES ({esc(sid)}, {esc(misspelling)}, 'MISSPELLING');")

    # Pass 4: Skill Relations
    sql.append("\n-- Technical Skill Relations")
    for s in skills:
        sid = s["skill_id"]
        for rel_id in s.get("related_skill_ids", []):
            if rel_id in skill_ids_set:
                sql.append(f"INSERT INTO technical_skill_relations (skill_id, related_skill_id, relation_type) VALUES ({esc(sid)}, {esc(rel_id)}, 'RELATED');")

    sql.append("")

    # Seed Roles
    sql.append("-- ========================================================")
    sql.append("-- SEED DATA: Roles / Designations (220 entries)")
    sql.append("-- ========================================================")
    with open(_ROLES_DIR / "seed_roles.json", encoding="utf-8") as f:
        roles = json.load(f)

    level_map = {"ENTRY": 1, "JUNIOR": 2, "MID": 3, "SENIOR": 4, "LEAD": 5, "PRINCIPAL": 6, "STAFF": 7, "MANAGER": 8, "DIRECTOR": 9, "VP": 10, "CXO": 11}

    for r in roles:
        rid = r["role_id"]
        dom_id = domain_map.get(r.get("domain"))
        lvl_id = level_map.get(r.get("seniority_level"))
        sql.append(
            f"INSERT INTO roles (role_id, canonical_title, normalized_title, role_family, domain_id, seniority_level_id, description, active) "
            f"VALUES ({esc(rid)}, {esc(r['canonical_title'])}, {esc(r['canonical_title'].strip().lower())}, {esc(r['role_family'])}, {esc(dom_id)}, {esc(lvl_id)}, {esc(r.get('description'))}, {esc(r.get('active', True))}) "
            f"ON CONFLICT (role_id) DO UPDATE SET canonical_title = EXCLUDED.canonical_title, normalized_title = EXCLUDED.normalized_title, role_family = EXCLUDED.role_family, domain_id = EXCLUDED.domain_id, seniority_level_id = EXCLUDED.seniority_level_id, description = EXCLUDED.description;"
        )

    # Role Aliases and Skill Relations
    sql.append("\n-- Role Aliases and Relations")
    for r in roles:
        rid = r["role_id"]
        for alias in r.get("aliases", []):
            sql.append(f"INSERT INTO role_aliases (role_id, alias_text) VALUES ({esc(rid)}, {esc(alias)});")
        for rel_skill in r.get("related_skill_ids", []):
            if rel_skill in skill_ids_set:
                sql.append(f"INSERT INTO role_skill_relations (role_id, skill_id, relation_type) VALUES ({esc(rid)}, {esc(rel_skill)}, 'RELATED');")

    sql.append("\n-- Schema & Seed script complete.\n")

    with open(_OUTPUT_FILE, "w", encoding="utf-8") as out:
        out.write("\n".join(sql))

    print(f"Successfully generated {_OUTPUT_FILE} with {len(sql)} lines of SQL.")


if __name__ == "__main__":
    generate_sql()
