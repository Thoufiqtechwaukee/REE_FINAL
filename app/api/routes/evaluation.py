from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import is_valid_resume_id
from app.db.session import get_db

router = APIRouter(prefix="/api/resumes/{resume_id}/evaluation", tags=["evaluation"])


@router.post("")
async def run_evaluation(resume_id: str, db: Session = Depends(get_db)):
    if not is_valid_resume_id(resume_id):
        raise HTTPException(status_code=400, detail="Invalid resume id")
    from app.evaluation.orchestrator import run_full_evaluation

    try:
        result = await run_full_evaluation(db, resume_id)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result


@router.get("")
def get_evaluation(resume_id: str, db: Session = Depends(get_db)):
    if not is_valid_resume_id(resume_id):
        raise HTTPException(status_code=400, detail="Invalid resume id")
    from app.db.models.evaluation import ResumeEvaluation

    row = (
        db.query(ResumeEvaluation)
        .filter(ResumeEvaluation.resume_id == resume_id)
        .order_by(ResumeEvaluation.created_at.desc())
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No evaluation found for this resume")
    from app.evaluation.orchestrator import evaluation_to_response

    return evaluation_to_response(db, row)
