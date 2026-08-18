"""Central runtime configuration, loaded once from environment/.env."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_REPO_ROOT / ".env", extra="ignore")

    runpod_endpoint_url: str = ""
    runpod_api_key: str = ""
    runpod_chat_model: str = "qwen2.5:14b"
    runpod_embedding_model: str = "nomic-embed-text"

    database_url: str = "mssql+pyodbc://@localhost/REEFinalDB?driver=ODBC+Driver+17+for+SQL+Server&trusted_connection=yes"

    @property
    def db_url(self) -> str:
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            return "postgresql://" + url[11:]
        return url

    storage_dir: str = "./storage"
    gap_threshold_months: int = 6

    embedding_expected_dimension: int = 768

    @property
    def storage_path(self) -> Path:
        p = (_REPO_ROOT / self.storage_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def resumes_dir(self) -> Path:
        p = self.storage_path / "resumes"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def faiss_dir(self) -> Path:
        p = self.storage_path / "faiss"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def chat_completions_url(self) -> str:
        base = self.runpod_endpoint_url.rstrip("/")
        return f"{base}/chat/completions"

    @property
    def embeddings_url(self) -> str:
        base = self.runpod_endpoint_url.rstrip("/")
        return f"{base}/embeddings"


@lru_cache
def get_settings() -> Settings:
    return Settings()
