"""Pipeline-internal dataclasses (spec §7) -- NOT ORM, NOT API schemas. These
carry data between extraction -> section mapping -> chunking before anything
is persisted."""
from dataclasses import dataclass, field


@dataclass
class BoundingBox:
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass
class Block:
    block_id: str
    page_number: int
    block_type: str  # "line" | "paragraph"
    text: str
    sequence: int
    heading_context: str | None = None
    bounding_box: BoundingBox | None = None


@dataclass
class Page:
    page_number: int
    raw_text: str
    normalized_text: str


@dataclass
class SectionAssignment:
    canonical_section: str
    confidence: float
    page_number: int
    sequence: int
    block_ids: list[str]
    text: str


@dataclass
class ResumeExtractionDocument:
    resume_id: str
    pages: list[Page] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    sections: list[SectionAssignment] = field(default_factory=list)
    reading_order: list[str] = field(default_factory=list)  # block_ids in order
    raw_text: str = ""
    normalized_text: str = ""
