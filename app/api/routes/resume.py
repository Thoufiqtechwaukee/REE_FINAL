from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import resume_to_schema, skill_to_schema
from app.core.security import is_valid_resume_id
from app.db.models.resume import Resume
from app.db.session import get_db
from app.schemas.resume import ResumeStatusResponse, ResumeUploadResponse
from app.services import resume_service
from app.services.skill_verification import list_skills_for_verification

router = APIRouter(prefix="/api/resumes", tags=["resumes"])

_MAX_PDF_BYTES = 20 * 1024 * 1024


@router.post("/upload", response_model=ResumeUploadResponse)
async def upload_resume(file: UploadFile, db: Session = Depends(get_db)):
    if file.content_type not in ("application/pdf", "application/x-pdf") and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(pdf_bytes) > _MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail="PDF exceeds maximum allowed size")

    resume = resume_service.upload_resume(db, file.filename, pdf_bytes)

    try:
        resume = await resume_service.process_until_skill_verification(db, resume.id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Processing failed at {resume.failed_stage}: {exc}") from exc

    skills = list_skills_for_verification(db, resume.id)
    return ResumeUploadResponse(
        resume=resume_to_schema(resume),
        skills=[skill_to_schema(s) for s in skills],
    )


@router.get("/{resume_id}", response_model=ResumeStatusResponse)
def get_resume_status(resume_id: str, db: Session = Depends(get_db)):
    if not is_valid_resume_id(resume_id):
        raise HTTPException(status_code=400, detail="Invalid resume id")
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume_to_schema(resume)


@router.get("/{resume_id}/document")
def get_resume_document(resume_id: str, db: Session = Depends(get_db)):
    if not is_valid_resume_id(resume_id):
        raise HTTPException(status_code=400, detail="Invalid resume id")
    resume = db.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Resume not found")
    from app.services.pdf_storage import load_pdf

    pdf_bytes = load_pdf(resume_id)
    return Response(content=pdf_bytes, media_type="application/pdf")
