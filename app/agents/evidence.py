"""
Evidence category (spec §36). For each verified skill: deterministic
distinct-source classification first (never mention-counting -- a skill
repeated six times in one bullet list must not outscore one real mention
elsewhere), then Qwen semantic validation only for skills that are still
WEAK/NONE after the deterministic pass, retrieved via RAG and capped at
MODERATE (vector similarity alone is never a positive verdict -- spec §36).
"""
import json
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agents.distinct_technology_guard import is_cross_technology_leak
from app.agents.prompts.evidence import EVIDENCE_VALIDATION_PROMPT
from app.agents.qwen_client import call_chat_json
from app.db.models.evaluation import EvidenceStrength, EvidenceType, ResumeSkill, ResumeSkillEvidence
from app.db.models.resume import ChunkType, ResumeChunk
from app.db.models.skill import TechnicalSkill
from app.retrieval.resume_retrieval import search_skill_evidence

logger = logging.getLogger(__name__)

_STRONG_ELIGIBLE_TYPES = {ChunkType.EXPERIENCE_RESPONSIBILITY.value, ChunkType.EXPERIENCE_PROJECT.value, ChunkType.PROJECT.value}
_MAX_EVIDENCE_LOCATIONS_PER_SKILL = 3


@dataclass
class SkillEvidenceResult:
    resume_skill: ResumeSkill
    strength: EvidenceStrength
    evidence_type: EvidenceType
    evidence_rows: list[ResumeSkillEvidence]


def _chunk_type_str(chunk: ResumeChunk) -> str:
    return chunk.chunk_type.value if hasattr(chunk.chunk_type, "value") else chunk.chunk_type


def _classify_deterministic(chunks: list[ResumeChunk]) -> tuple[EvidenceStrength, EvidenceType, list[ResumeChunk]]:
    strong_sources: dict[tuple[str, str | None], ResumeChunk] = {}
    tech_chunks, cert_chunks, skills_section_chunks, summary_chunks = [], [], [], []

    for c in chunks:
        ctype = _chunk_type_str(c)
        if ctype in _STRONG_ELIGIBLE_TYPES:
            key = (ctype, c.company)
            strong_sources.setdefault(key, c)
        elif ctype == ChunkType.EXPERIENCE_TECHNOLOGY.value:
            tech_chunks.append(c)
        elif ctype == ChunkType.CERTIFICATION.value:
            cert_chunks.append(c)
        elif ctype == ChunkType.SKILL_SECTION.value:
            skills_section_chunks.append(c)
        elif ctype == ChunkType.SUMMARY.value:
            summary_chunks.append(c)

    if len(strong_sources) >= 2:
        return EvidenceStrength.STRONG, EvidenceType.EXPLICIT_IMPLEMENTATION, list(strong_sources.values())
    if len(strong_sources) == 1:
        return EvidenceStrength.MODERATE, EvidenceType.RESPONSIBILITY_USAGE, list(strong_sources.values())
    if tech_chunks:
        return EvidenceStrength.WEAK, EvidenceType.TECHNICAL_ENVIRONMENT, tech_chunks[:1]
    if cert_chunks:
        return EvidenceStrength.WEAK, EvidenceType.CERTIFICATION_ONLY, cert_chunks[:1]
    if summary_chunks:
        return EvidenceStrength.WEAK, EvidenceType.RESPONSIBILITY_USAGE, summary_chunks[:1]
    if skills_section_chunks:
        return EvidenceStrength.WEAK, EvidenceType.SKILLS_SECTION_ONLY, skills_section_chunks[:1]
    return EvidenceStrength.NONE, EvidenceType.NONE, []


async def _validate_weak_none_via_qwen(
    db: Session, resume_id: str, weak_none_skills: list[ResumeSkill], skill_by_id: dict[str, TechnicalSkill]
) -> dict[str, dict]:
    """Batched RAG + Qwen validation for skills still WEAK/NONE after the
    deterministic pass. Returns skill_id -> verdict dict, or {} entries
    missing for skills Qwen gave no usable verdict for (kept as-is by caller)."""
    if not weak_none_skills:
        return {}

    per_skill_passages: dict[str, list[dict]] = {}
    for rs in weak_none_skills:
        skill = skill_by_id.get(rs.skill_id)
        if skill is None:
            continue
        hits = await search_skill_evidence(db, resume_id, skill.canonical_name, top_k=5)
        if hits:
            per_skill_passages[rs.skill_id] = [
                {"chunk_id": h.chunk_id, "text": h.original_text} for h in hits
            ]

    if not per_skill_passages:
        return {}

    # Qwen is given a local passage_index per passage (never the real
    # chunk_id UUID -- keeping the prompt payload clean) and asked to echo
    # that index back; the real chunk_id is resolved locally afterward. This
    # is deliberate: asking Qwen for a "source_chunk_id" it was never shown
    # only invites a hallucinated id that would violate the FK to
    # resume_chunks on insert -- a real bug this design avoids by construction.
    payload = {
        "skills": [
            {
                "skill": skill_by_id[skill_id].canonical_name,
                "passages": [{"passage_index": i, "text": p["text"]} for i, p in enumerate(passages)],
            }
            for skill_id, passages in per_skill_passages.items()
        ]
    }
    chunk_ids_by_skill_name = {
        skill_by_id[skill_id].canonical_name: [p["chunk_id"] for p in passages]
        for skill_id, passages in per_skill_passages.items()
    }

    data = await call_chat_json(EVIDENCE_VALIDATION_PROMPT, json.dumps(payload))
    verdicts: dict[str, dict] = {}
    if not isinstance(data, dict):
        return verdicts

    name_to_skill_id = {s.canonical_name: sid for sid, s in skill_by_id.items()}
    for row in data.get("results", []):
        if not isinstance(row, dict):
            continue
        skill_name = row.get("skill")
        skill_id = name_to_skill_id.get(skill_name)
        if skill_id is None:
            continue
        strength = row.get("evidence_strength", "NONE")
        if strength not in ("MODERATE", "WEAK", "NONE"):
            strength = "NONE"  # hard cap -- Qwen may never assign STRONG
        explanation = row.get("explanation", "") or ""
        if strength != "NONE" and is_cross_technology_leak(skill_id, explanation, {sid: s.canonical_name for sid, s in skill_by_id.items()}):
            strength = "NONE"  # guard rejected -- cited a sibling technology instead

        chunk_ids = chunk_ids_by_skill_name.get(skill_name, [])
        source_chunk_id = None
        passage_index = row.get("passage_index")
        if strength != "NONE" and isinstance(passage_index, int) and 0 <= passage_index < len(chunk_ids):
            source_chunk_id = chunk_ids[passage_index]
        elif strength != "NONE" and chunk_ids:
            source_chunk_id = chunk_ids[0]  # index missing/invalid -- fall back to the top retrieved passage
        if strength != "NONE" and source_chunk_id is None:
            strength = "NONE"  # no real chunk to attribute this to -- never persist unattributable evidence

        verdicts[skill_id] = {
            "strength": strength,
            "evidence_type": row.get("evidence_type", "NONE"),
            "evidence_text": row.get("evidence_text", ""),
            "source_chunk_id": source_chunk_id,
            "explanation": explanation,
        }
    return verdicts


async def analyze_evidence(db: Session, resume_id: str) -> list[SkillEvidenceResult]:
    verified_skills = (
        db.query(ResumeSkill)
        .filter(ResumeSkill.resume_id == resume_id, ResumeSkill.verification_status != "USER_REMOVED")
        .all()
    )
    if not verified_skills:
        return []

    skill_ids = [rs.skill_id for rs in verified_skills]
    skills = db.query(TechnicalSkill).filter(TechnicalSkill.skill_id.in_(skill_ids)).all()
    skill_by_id = {s.skill_id: s for s in skills}

    db.query(ResumeSkillEvidence).filter(
        ResumeSkillEvidence.resume_skill_id.in_([rs.id for rs in verified_skills])
    ).delete(synchronize_session=False)

    all_chunk_ids = {cid for rs in verified_skills for cid in (rs.source_chunk_ids or [])}
    chunks_by_id = {}
    if all_chunk_ids:
        rows = db.query(ResumeChunk).filter(ResumeChunk.chunk_id.in_(all_chunk_ids)).all()
        chunks_by_id = {c.chunk_id: c for c in rows}

    results: list[SkillEvidenceResult] = []
    weak_none: list[ResumeSkill] = []
    deterministic: dict[str, tuple[EvidenceStrength, EvidenceType, list[ResumeChunk]]] = {}

    for rs in verified_skills:
        source_chunks = [chunks_by_id[cid] for cid in (rs.source_chunk_ids or []) if cid in chunks_by_id]
        strength, evidence_type, contributing = _classify_deterministic(source_chunks)
        deterministic[rs.id] = (strength, evidence_type, contributing)
        if strength in (EvidenceStrength.WEAK, EvidenceStrength.NONE):
            weak_none.append(rs)

    qwen_verdicts = await _validate_weak_none_via_qwen(db, resume_id, weak_none, skill_by_id)

    for rs in verified_skills:
        strength, evidence_type, contributing = deterministic[rs.id]
        evidence_rows: list[ResumeSkillEvidence] = []

        verdict = qwen_verdicts.get(rs.skill_id)
        if verdict and EvidenceStrength[verdict["strength"]].value != "NONE":
            new_strength = EvidenceStrength[verdict["strength"]]
            # Only upgrade, never downgrade a deterministic finding.
            rank = {"NONE": 0, "WEAK": 1, "MODERATE": 2, "STRONG": 3}
            if rank[new_strength.value] > rank[strength.value]:
                strength = new_strength
                evidence_type = EvidenceType.INFERRED
            fallback_chunk_id = contributing[0].chunk_id if contributing else None
            row = ResumeSkillEvidence(
                resume_skill_id=rs.id,
                chunk_id=verdict["source_chunk_id"] or fallback_chunk_id,
                evidence_type=evidence_type,
                evidence_strength=strength,
                qwen_explanation=verdict["explanation"],
                confidence=0.6,
            )
            if row.chunk_id:
                db.add(row)
                evidence_rows.append(row)

        for c in contributing[:_MAX_EVIDENCE_LOCATIONS_PER_SKILL]:
            row = ResumeSkillEvidence(
                resume_skill_id=rs.id,
                chunk_id=c.chunk_id,
                evidence_type=evidence_type,
                evidence_strength=strength,
                qwen_explanation=None,
                confidence=1.0,
            )
            db.add(row)
            evidence_rows.append(row)

        results.append(SkillEvidenceResult(resume_skill=rs, strength=strength, evidence_type=evidence_type, evidence_rows=evidence_rows))

    db.commit()
    return results
