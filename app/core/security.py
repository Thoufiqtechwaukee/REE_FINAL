"""
Resume-scoping and storage-path safety helpers (spec §53). There is no user
login in this system -- the security boundary is that every retrieval/storage
operation is keyed by an opaque resume_id (UUID) and no path is ever built
from client-controlled strings.
"""
import re
import uuid
from pathlib import Path

_SAFE_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def new_resume_id() -> str:
    return str(uuid.uuid4())


def is_valid_resume_id(resume_id: str) -> bool:
    if not resume_id or not _SAFE_UUID.match(resume_id):
        return False
    try:
        uuid.UUID(resume_id)
        return True
    except ValueError:
        return False


def resume_pdf_path(storage_resumes_dir: Path, resume_id: str) -> Path:
    """Builds the on-disk PDF path for a resume_id, never from client input
    directly (the id is validated as a UUID first, so no path traversal is
    possible)."""
    if not is_valid_resume_id(resume_id):
        raise ValueError("Invalid resume_id")
    return storage_resumes_dir / f"{resume_id}.pdf"


class CrossResumeAccessError(Exception):
    """Raised when a query attempts to touch a resume_id it wasn't scoped to."""


def assert_scoped(expected_resume_id: str, actual_resume_id: str) -> None:
    if expected_resume_id != actual_resume_id:
        raise CrossResumeAccessError(
            f"Attempted cross-resume access: expected {expected_resume_id}, got {actual_resume_id}"
        )
