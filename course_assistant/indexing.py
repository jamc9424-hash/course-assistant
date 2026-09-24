"""Separate indexes for keyword, text-vector, and visual-vector retrieval.

Design choice (documented in README): we keep the three indexes independent as
the assignment requires, but use a lightweight NumPy cosine store rather than
chromadb to keep the install and incremental tests fast and dependency-light
(chromadb would pull a large native stack). Persistence is JSON + .npy in the
gitignored data dir. Swap for chromadb later without changing callers.

Document removal drops the doc's vectors and chunks from every store, so later
queries cannot rely on removed content.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .types import SourceLocation, TextChunk, VisualRecord


class CosineVectorStore:
    """NumPy cosine similarity store with add/remove/persist."""

    def __init__(self, path: Path, dim: int = 0):
        self.path = Path(path)
        self.dim = dim or 0                       # 0 = learn from first add/file
        self.vectors: dict[str, np.ndarray] = {}
        self.keys: list[str] = []          # insertion order for index mapping
        self._order_file = self.path.with_suffix(self.path.suffix + ".keys.json")
        self._load()

    # ---- persistence ---------------------------------------------------
    def _load(self) -> None:
        if self.path.is_file():
            arr = np.load(self.path, allow_pickle=False)
            self.dim = arr.shape[1]
            keys = self._read_order() or [f"vec_{i}" for i in range(arr.shape[0])]
            if len(keys) != arr.shape[0]:
                keys = [f"vec_{i}" for i in range(arr.shape[0])]
            for i, row in enumerate(arr):
                self.vectors[keys[i]] = row
                self.keys.append(keys[i])
        self._idx = {k: i for i, k in enumerate(self.keys)}

    def _read_order(self) -> Optional[list[str]]:
        import json
        if self._order_file.is_file():
            try:
                return json.loads(self._order_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def save(self) -> None:
        if not self.vectors:
            return
        order = np.vstack([self.vectors[k] for k in self.keys])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.save(self.path, order)
        if self.keys and any(not k.startswith("vec_") for k in self.keys):
            import json
            self._order_file.write_text(json.dumps(self.keys), encoding="utf-8")
        elif self._order_file.is_file():
            self._order_file.unlink(missing_ok=True)

    # ---- writes --------------------------------------------------------
    def add(self, vector: list[float], key: Optional[str] = None) -> str:
        key = key or f"vec_{len(self.keys)}"
        v = np.asarray(vector, dtype="float32")
        v = v.reshape(-1)
        if not self.dim:
            self.dim = v.shape[0]
        if v.shape != (self.dim,):
            raise ValueError(f"vector dim {v.shape} != expected {self.dim}")
        if key in self.vectors:
            self.vectors[key] = v
        else:
            self.vectors[key] = v
            self.keys.append(key)
        self._idx = {k: i for i, k in enumerate(self.keys)}
        return key

    def remove_by_keys(self, keys: set[str]) -> None:
        self.keys = [k for k in self.keys if k not in keys]
        self.vectors = {k: self.vectors[k] for k in self.keys}
        self._idx = {k: i for i, k in enumerate(self.keys)}

    def wipe(self) -> None:
        self.keys = []
        self.vectors = {}
        self._idx = {}
        if self.path.exists():
            self.path.unlink()
        if self._order_file.exists():
            self._order_file.unlink()

    # ---- query ---------------------------------------------------------
    def search(self, query: list[float], top_k: int = 5) -> list[tuple[str, float]]:
        if not self.keys:
            return []
        q = np.asarray(query, dtype="float32").reshape(1, -1)
        mat = np.vstack([self.vectors[k] for k in self.keys])
        qn = np.linalg.norm(q)
        if qn == 0:
            return []
        scores = (mat @ q.T).ravel() / (np.linalg.norm(mat, axis=1) * qn)
        top = min(top_k, len(self.keys))
        order = np.argsort(-scores)[:top]
        return [(self.keys[int(i)], float(scores[int(i)])) for i in order]


class KeywordIndex:
    """BM25 index over text chunks (bm25s), persisted as json + npy."""

    def __init__(self, path: Path):
        self.path = Path(path)
        # chunk_id -> TextChunk payload
        self.chunks: dict[str, TextChunk] = {}
        self._load()

    def _load(self) -> None:
        meta = self.path / "chunks.json"
        if meta.is_file():
            data = json.loads(meta.read_text(encoding="utf-8"))
            for item in data:
                self.chunks[item["chunk_id"]] = TextChunk(**{**item})

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        data = [c.to_dict() for c in self.chunks.values()]
        (self.path / "chunks.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def _assign_ids(self, chunks: list[TextChunk]) -> list[TextChunk]:
        out = []
        for i, c in enumerate(chunks):
            if not c.chunk_id:
                c.chunk_id = f"c{i:06d}"
            out.append(c)
        return out

    def rebuild(self, chunks: list[TextChunk]) -> None:
        """Build the BM25 index from scratch for the current chunk set."""
        try:
            import bm25s
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"bm25s not installed: {e}") from e
        chunks = self._assign_ids(list(chunks))
        self.chunks = {c.chunk_id: c for c in chunks}
        if not chunks:
            self._corpus = None
            self._index = None
            self.save()
            return
        texts = [c.text for c in chunks]
        corpus = bm25s.tokenize(texts, return_ids=False)
        index = bm25s.BM25()
        index.index(corpus)
        self._corpus = corpus
        self._index = index
        self.save()

    def search(self, query: str, top_k: int = 5) -> list[tuple[str, float]]:
        if not self.chunks or getattr(self, "_index", None) is None:
            return []
        q = __import__("bm25s").tokenize([query], return_ids=False)
        results, scores = self._index.retrieve(q, k=min(top_k, len(self.chunks)))
        out: list[tuple[str, float]] = []
        # results shape (1, k)
        for col_idx in range(results.shape[1]):
            chunk_pos = results[0, col_idx]
            score = scores[0, col_idx]
            chunk_id = list(self.chunks.keys())[int(chunk_pos)]
            out.append((chunk_id, float(score)))
        return out

    def remove_by_doc(self, document: str) -> set[str]:
        removed = {cid for cid, c in self.chunks.items() if c.document == document}
        for cid in removed:
            self.chunks.pop(cid, None)
        self.rebuild(list(self.chunks.values()))
        return removed
