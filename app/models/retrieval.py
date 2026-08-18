from dataclasses import dataclass, field
from datetime import date


@dataclass
class RetrievalFilter:
    section: str | None = None
    chunk_type: str | None = None
    company: str | None = None
    role_canonical_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None


@dataclass
class RetrievalResult:
    chunk_id: str
    resume_id: str
    score: float
    chunk_type: str
    section: str
    company: str | None
    role_raw: str | None
    role_canonical_id: str | None
    page_number: int
    original_text: str
    start_date: date | None = None
    end_date: date | None = None
