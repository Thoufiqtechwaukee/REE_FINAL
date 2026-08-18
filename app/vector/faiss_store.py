"""
FaissVectorStore (spec §13). One reusable class backing three separate,
never-mixed index files (resume chunks / skill catalog / role catalog --
spec §20). FAISS is not the source of truth: every vector_id is persisted in
SQL Server against its owning chunk_id/skill_id/role_id, and rebuild()
regenerates the index purely from a caller-supplied id/vector iterable read
back out of SQL Server.

IndexIDMap2 over IndexFlatIP (exact, brute-force) -- cosine similarity via
pre-normalized vectors (see embeddings/nomic_client.py). Per-resume/catalog
corpora here are small (tens to low thousands of vectors), so exact search is
the right choice per the prior system's own conclusion, not an IVF/HNSW index.
"""
import threading
from pathlib import Path

import faiss
import numpy as np


class FaissVectorStore:
    def __init__(self, index_path: Path, dimension: int):
        self.index_path = index_path
        self.dimension = dimension
        self._lock = threading.Lock()
        self._index: faiss.IndexIDMap2 | None = None

    def _new_empty_index(self) -> faiss.IndexIDMap2:
        base = faiss.IndexFlatIP(self.dimension)
        return faiss.IndexIDMap2(base)

    def create_index(self) -> None:
        with self._lock:
            self._create_index_locked()
            self._save_locked()

    def _create_index_locked(self) -> None:
        self._index = self._new_empty_index()

    def load_index(self) -> None:
        with self._lock:
            self._load_index_locked()

    def _load_index_locked(self) -> None:
        if self.index_path.exists():
            self._index = faiss.read_index(str(self.index_path))
        else:
            self._index = self._new_empty_index()

    def _ensure_loaded(self) -> faiss.IndexIDMap2:
        """Must only be called while `self._lock` is already held -- this
        loads without re-acquiring the lock (threading.Lock is not
        reentrant; re-acquiring it from the same thread deadlocks)."""
        if self._index is None:
            self._load_index_locked()
        return self._index

    def save_index(self) -> None:
        with self._lock:
            self._save_locked()

    def _save_locked(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(self.index_path))

    def add_vectors(self, ids: list[int], vectors: np.ndarray) -> None:
        if len(ids) == 0:
            return
        if vectors.shape[1] != self.dimension:
            raise ValueError(f"Vector dimension {vectors.shape[1]} != index dimension {self.dimension}")
        with self._lock:
            index = self._ensure_loaded()
            id_arr = np.array(ids, dtype=np.int64)
            # Remove any existing rows for these ids first (add_with_ids does
            # not upsert -- a re-embed of an existing chunk must replace, not
            # duplicate, its vector).
            index.remove_ids(id_arr)
            index.add_with_ids(vectors.astype(np.float32), id_arr)
            self._save_locked()

    def search(self, query_vector: np.ndarray, top_k: int, allowed_ids: set[int] | None = None) -> list[tuple[int, float]]:
        with self._lock:
            index = self._ensure_loaded()
            if index.ntotal == 0:
                return []
            query = query_vector.astype(np.float32).reshape(1, -1)
            # Over-fetch when filtering by allowed_ids so a resume-scoped
            # query still returns top_k *within that resume* rather than
            # being starved by other resumes' closer vectors.
            fetch_k = top_k if allowed_ids is None else min(index.ntotal, max(top_k * 20, top_k + 50))
            scores, ids = index.search(query, fetch_k)

        results: list[tuple[int, float]] = []
        for vec_id, score in zip(ids[0], scores[0]):
            if vec_id == -1:
                continue
            if allowed_ids is not None and int(vec_id) not in allowed_ids:
                continue
            results.append((int(vec_id), float(score)))
            if len(results) >= top_k:
                break
        return results

    def delete_ids(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            index = self._ensure_loaded()
            index.remove_ids(np.array(ids, dtype=np.int64))
            self._save_locked()

    def rebuild(self, id_vector_pairs: list[tuple[int, np.ndarray]]) -> None:
        with self._lock:
            self._index = self._new_empty_index()
            if id_vector_pairs:
                ids = np.array([p[0] for p in id_vector_pairs], dtype=np.int64)
                vectors = np.array([p[1] for p in id_vector_pairs], dtype=np.float32)
                self._index.add_with_ids(vectors, ids)
            self._save_locked()

    def health_check(self) -> dict:
        with self._lock:
            index = self._ensure_loaded()
            return {
                "path": str(self.index_path),
                "exists_on_disk": self.index_path.exists(),
                "ntotal": index.ntotal,
                "dimension": self.dimension,
            }
