"""Secure original PDF storage (spec §53). Files live outside any
web-servable directory; the only access path is through the resume_id-scoped
API route, which streams the file rather than exposing a raw path."""
import hashlib

from app.core.config import get_settings
from app.core.security import resume_pdf_path


def compute_pdf_hash(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()


def save_pdf(resume_id: str, pdf_bytes: bytes) -> str:
    settings = get_settings()
    path = resume_pdf_path(settings.resumes_dir, resume_id)
    path.write_bytes(pdf_bytes)
    return str(path)


def load_pdf(resume_id: str) -> bytes:
    settings = get_settings()
    path = resume_pdf_path(settings.resumes_dir, resume_id)
    return path.read_bytes()
