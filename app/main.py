from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import evaluation as evaluation_routes
from app.api.routes import resume as resume_routes
from app.api.routes import skills as skills_routes
from app.core.logging import configure_logging

configure_logging()

app = FastAPI(title="REE FINAL - Resume Depth Evaluation Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(resume_routes.router)
app.include_router(skills_routes.router)
app.include_router(evaluation_routes.router)


@app.get("/api/health")
async def health():
    from app.agents.qwen_client import health_check as qwen_health
    from app.embeddings.nomic_client import health_check as nomic_health

    qwen_ok = await qwen_health()
    nomic_ok = await nomic_health()
    return {"qwen": qwen_ok, "nomic": nomic_ok}


# Mounted last and deliberately: Starlette matches routes in registration
# order, and a Mount("/", ...) matches every path prefix -- registering it
# before /api/* routes would greedily shadow all of them (a real bug caught
# by testing the live server, not just importing the app object).
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
