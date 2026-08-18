"""Pipeline-internal chunk draft (spec §9) -- produced by chunking, consumed
by embeddings/contextualizer before ever becoming a ResumeChunk ORM row."""
from dataclasses import dataclass, field
from datetime import date


@dataclass
class ChunkDraft:
    chunk_type: str
    section: str
    original_text: str
    page_number: int
    sequence: int
    source_block_ids: list[str] = field(default_factory=list)
    company: str | None = None
    role_raw: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_current: bool = False
    parent_sequence: int | None = None  # link to another ChunkDraft.sequence, resolved to chunk_id at persist time
    embedding_text: str = ""
