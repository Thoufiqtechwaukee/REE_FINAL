"""Builds embedding_text per chunk using the exact contextual template from
spec §11 -- never embeds isolated sentences without context. original_text is
always preserved separately; evidence shown to the user must use original_text,
never embedding_text (spec §11)."""
from app.models.chunk import ChunkDraft


def build_embedding_text(chunk: ChunkDraft, *, candidate_name: str | None) -> str:
    parts = []
    if candidate_name:
        parts.append(f"Candidate:\n{candidate_name}")
    if chunk.company:
        parts.append(f"Company:\n{chunk.company}")
    if chunk.role_raw:
        parts.append(f"Role:\n{chunk.role_raw}")
    if chunk.start_date or chunk.end_date:
        start = chunk.start_date.isoformat() if chunk.start_date else "?"
        end = "Present" if chunk.is_current else (chunk.end_date.isoformat() if chunk.end_date else "?")
        parts.append(f"Dates:\n{start} to {end}")
    parts.append(f"Section:\n{chunk.section}")
    parts.append(f"Chunk Type:\n{chunk.chunk_type}")
    parts.append(f"Original Text:\n{chunk.original_text}")
    return "\n\n".join(parts)


def apply_embedding_text(chunks: list[ChunkDraft], *, candidate_name: str | None) -> None:
    for chunk in chunks:
        chunk.embedding_text = build_embedding_text(chunk, candidate_name=candidate_name)
