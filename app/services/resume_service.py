"""
Pre-verification pipeline stages (spec §4 flow, up through the skill
verification gate): upload -> extraction -> section mapping -> chunking ->
embeddings -> FAISS indexing -> skill discovery -> WAITING_FOR_SKILL_
VERIFICATION. Everything past the gate (role normalization, experience,
evidence/growth/completeness, scoring, final justification) lives in
evaluation/orchestrator.py, which only ever starts once SKILLS_VERIFIED is
reached (spec §5's hard gate).
"""
import logging

from sqlalchemy.orm import Session

from app.agents.skill_discovery import discover_skills
from app.chunking import chunker, contextualizer
from app.core.versioning import CHUNKING_VERSION
from app.db.models.resume import Resume, ResumeChunk, ResumeExtraction, ResumeSection, ResumeStatus
from app.embeddings.nomic_client import embed_batch
from app.extraction import pdf_extractor, section_mapper
from app.services import pdf_storage
from app.services.skill_verification import persist_discovered_skills
from app.vector.index_manager import resume_index, vector_id_for

logger = logging.getLogger(__name__)


def _fail(db: Session, resume: Resume, stage: str, exc: Exception) -> None:
    logger.exception("Resume %s failed at stage %s", resume.id, stage)
    resume.status = ResumeStatus.FAILED
    resume.failed_stage = stage
    resume.failure_reason = str(exc)[:2000]
    db.commit()


def upload_resume(db: Session, filename: str, pdf_bytes: bytes) -> Resume:
    resume = Resume(
        filename=filename,
        pdf_hash=pdf_storage.compute_pdf_hash(pdf_bytes),
        storage_path="",
        status=ResumeStatus.UPLOADED,
    )
    db.add(resume)
    db.commit()

    storage_path = pdf_storage.save_pdf(resume.id, pdf_bytes)
    resume.storage_path = storage_path
    db.commit()
    return resume


async def process_until_skill_verification(db: Session, resume_id: str) -> Resume:
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise ValueError("Resume not found")

    pdf_bytes = pdf_storage.load_pdf(resume_id)

    try:
        doc = pdf_extractor.extract(resume_id, pdf_bytes)
    except Exception as exc:
        _fail(db, resume, "extraction", exc)
        raise

    resume.page_count = len(doc.pages)
    extraction_row = ResumeExtraction(
        resume_id=resume_id,
        raw_text=doc.raw_text,
        normalized_text=doc.normalized_text,
        blocks=[
            {
                "block_id": b.block_id,
                "page_number": b.page_number,
                "block_type": b.block_type,
                "text": b.text,
                "sequence": b.sequence,
                "heading_context": b.heading_context,
                "bounding_box": (
                    {"x0": b.bounding_box.x0, "x1": b.bounding_box.x1, "top": b.bounding_box.top, "bottom": b.bounding_box.bottom}
                    if b.bounding_box
                    else None
                ),
            }
            for b in doc.blocks
        ],
        reading_order=doc.reading_order,
        extraction_version="extraction-v1",
    )
    db.add(extraction_row)
    resume.status = ResumeStatus.EXTRACTED
    db.commit()

    try:
        section_result = section_mapper.map_blocks_to_sections(doc.blocks)
        for s in section_result.sections:
            db.add(
                ResumeSection(
                    resume_id=resume_id,
                    canonical_section=s.canonical_section,
                    confidence=s.confidence,
                    page_number=s.page_number,
                    sequence=s.sequence,
                    block_ids=s.block_ids,
                    text=s.text,
                )
            )
        db.commit()

        drafts = chunker.chunk_document(doc, section_result)
        candidate_name = _guess_candidate_name(doc)
        contextualizer.apply_embedding_text(drafts, candidate_name=candidate_name)
    except Exception as exc:
        _fail(db, resume, "chunking", exc)
        raise

    # Embeddings/FAISS are a hard dependency here (not a gracefully-degradable
    # evaluation-time agent) -- without them there is no semantic index to do
    # RAG-based evidence/skill discovery against at all, so a failure here
    # fails the whole resume rather than continuing with a broken index.
    try:
        texts = [d.embedding_text for d in drafts]
        vectors = await embed_batch(texts) if texts else None

        seq_to_chunk_id: dict[int, str] = {}
        chunk_rows: list[tuple[ResumeChunk, object]] = []
        for i, d in enumerate(drafts):
            row = ResumeChunk(
                resume_id=resume_id,
                chunk_type=d.chunk_type,
                section=d.section,
                company=d.company,
                role_raw=d.role_raw,
                start_date=d.start_date,
                end_date=d.end_date,
                is_current=d.is_current,
                page_number=d.page_number,
                sequence=d.sequence,
                original_text=d.original_text,
                embedding_text=d.embedding_text,
                embedding_model="nomic-embed-text",
                embedding_version=CHUNKING_VERSION,
                embedding_dimension=768,
            )
            db.add(row)
            db.flush()
            seq_to_chunk_id[d.sequence] = row.chunk_id
            row.vector_id = vector_id_for(row.chunk_id)
            chunk_rows.append((row, d))

        for row, d in chunk_rows:
            if d.parent_sequence is not None:
                row.parent_chunk_id = seq_to_chunk_id.get(d.parent_sequence)
        db.commit()

        if chunk_rows:
            ids = [row.vector_id for row, _ in chunk_rows]
            resume_index().add_vectors(ids, vectors)

        resume.status = ResumeStatus.INDEXED
        db.commit()
    except Exception as exc:
        _fail(db, resume, "embedding", exc)
        raise

    try:
        persisted_chunks = db.query(ResumeChunk).filter(ResumeChunk.resume_id == resume_id).all()
        discovered = await discover_skills(db, persisted_chunks)
        persist_discovered_skills(db, resume_id, discovered)
        resume.status = ResumeStatus.WAITING_FOR_SKILL_VERIFICATION
        db.commit()
    except Exception as exc:
        _fail(db, resume, "skill_discovery", exc)
        raise

    return resume


def _guess_candidate_name(doc) -> str | None:
    if not doc.blocks:
        return None
    first = doc.blocks[0].text.strip()
    if first and "@" not in first and len(first) <= 60 and not any(c.isdigit() for c in first):
        return first
    return None
