from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import evaluation as evaluation_routes
from app.api.routes import resume as resume_routes
from app.api.routes import skills as skills_routes
from app.core.logging import configure_logging

configure_logging()
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        import app.db.models  # Register all models
        from app.db.base import Base
        from app.db.session import SessionLocal, engine
        from app.vector.index_manager import skill_index

        Base.metadata.create_all(bind=engine)
        logger.info("Database tables initialized successfully.")

        if skill_index()._index is None or skill_index()._index.ntotal == 0:
            logger.info("Initializing FAISS catalog vector indices...")
            db = SessionLocal()
            try:
                from scripts.embed_catalogs import embed_roles, embed_skills
                await embed_skills(db)
                await embed_roles(db)
                logger.info("FAISS catalog indices initialized successfully.")
            except Exception as e:
                logger.warning(f"Catalog embedding auto-seed warning: {e}")
            finally:
                db.close()
    except Exception as exc:
        logger.warning(f"Database auto-init warning: {exc}")
    yield


app = FastAPI(title="REE FINAL - Resume Depth Evaluation Engine", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback

    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Server Error ({type(exc).__name__}): {exc}", "traceback": traceback.format_exc()},
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
