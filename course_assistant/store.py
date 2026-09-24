"""CourseAssistant orchestrator: document management + query + quiz + persistence.

Responsibilities
----------------
* Add documents (dedupe by content hash — same file loaded twice is a no-op).
* Remove documents (drops their chunks, vectors, and page images from every
  index so later answers cannot rely on removed content).
* Persist everything under the gitignored data dir so a restart restores the app.
* Expose high-level ``answer()`` and ``quiz()`` used by the Gradio UI and tests.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Optional

from . import chunking, config, parsing, service
from .config import Settings
from .generation import AnswerGenerator, GenerationError, QuizGenerator
from .indexing import CosineVectorStore, KeywordIndex
from .retrieval import HybridRetriever
from .types import Answer, QuizQuestion


class DocumentError(RuntimeError):
    pass


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


class CourseAssistant:
    def __init__(self, settings: Optional[Settings] = None):
        self.s = settings or config.load_settings()
        data = self.s.data_dir
        self.index_dir = data / "indexes"
        self.index_dir.mkdir(parents=True, exist_ok=True)

        self.text_store = CosineVectorStore(self.index_dir / "text_vectors.npy")
        self.visual_store = CosineVectorStore(self.index_dir / "visual_vectors.npy")
        self.keyword = KeywordIndex(self.index_dir / "keyword")

        self.llm = service.VisionLLMClient(self.s)
        self.text_emb = service.TextEmbeddingClient(self.s)
        self.visual_emb = service.VisualEmbeddingClient(self.s)
        self.rerank = service.RerankClient(self.s)
        self.parser = service.DocumentParserClient(self.s)

        self.retriever = HybridRetriever(
            self.s, self.keyword, self.text_store, self.visual_store,
            self.text_emb, self.visual_emb, self.rerank,
        )
        self.answers = AnswerGenerator(self.llm)
        self.quizzes = QuizGenerator(self.llm)
        self.manifest_path = data / "manifest.json"
        self.manifest = self._load_manifest()

    # ---- persistence helpers -------------------------------------------
    def _load_manifest(self) -> dict:
        if self.manifest_path.is_file():
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        return {}

    def _save_manifest(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(
            json.dumps(self.manifest, indent=2), encoding="utf-8"
        )

    def _save_visual_records(self, records: dict[str, dict]) -> None:
        path = self.visual_store.path.with_suffix(".records.json")
        path.write_text(json.dumps(records, indent=2), encoding="utf-8")

    def _load_visual_records(self) -> dict[str, dict]:
        path = self.visual_store.path.with_suffix(".records.json")
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    def save_all(self) -> None:
        self.text_store.save()
        self.visual_store.save()
        self.keyword.save()
        self._save_manifest()

    # ---- document management -------------------------------------------
    def list_documents(self) -> list[dict]:
        docs = []
        for doc_id, info in self.manifest.items():
            docs.append({
                "id": doc_id,
                "title": info.get("title"),
                "source_name": info.get("source_name"),
                "added": info.get("added"),
                "chunks": info.get("num_chunks", 0),
                "pages": info.get("num_pages", 0),
                "images": info.get("num_images", 0),
            })
        docs.sort(key=lambda d: d.get("title", "").lower())
        return docs

    def find_by_title(self, title: str) -> Optional[dict]:
        for info in self.manifest.values():
            if info.get("title") == title:
                return info
        return None

    def add_file(self, path) -> dict:
        """Ingest a file. Idempotent: same content is not indexed twice."""
        path = Path(path)
        if not path.is_file():
            raise DocumentError(f"file not found: {path}")
        digest = _file_hash(path)
        # dedupe by content hash
        for doc_id, info in self.manifest.items():
            if info.get("sha256") == digest:
                return {"status": "duplicate", "title": info.get("title"),
                        "doc_id": doc_id}
        # title collision on different content -> we still allow (keep both titles
        # unique by suffixing if needed) but that is rare; use stem.
        title = path.stem

        out_dir = self.s.data_dir / "parsed" / title
        try:
            parsed = parsing.parse_document(
                path, out_dir, parser=self.parser, allow_libreoffice=True
            )
        except parsing.UnsupportedFormatError as e:
            raise DocumentError(str(e)) from e

        pages = parsed.pages
        chunks = chunking.chunk_pages(
            pages, parsed.title, self.s.chunk_size, self.s.chunk_overlap
        )

        # keyword index
        self.keyword.rebuild(list(self.keyword.chunks.values()) + chunks)

        # text vectors
        text_ids: list[str] = []
        if chunks and self.s.use_text_vector:
            try:
                vecs = self.text_emb.embed([c.text for c in chunks])
                for c, v in zip(chunks, vecs):
                    key = c.chunk_id
                    self.text_store.add(v, key=key)
                    text_ids.append(key)
            except service.ServiceError as e:
                raise DocumentError(f"text embedding service unavailable: {e}") from e

        # visual records + vectors
        vis_records = dict(self._load_visual_records())
        image_keys: list[str] = []
        for i, page in enumerate(pages):
            if page.image_path:
                vid = f"{title}:p{page.index + 1}"
                vis_records[vid] = {
                    "document": parsed.title,
                    "page": page.index + 1,
                    "section": page.section,
                    "image_path": page.image_path,
                    "image_mime": "image/png",
                    "caption": (page.section or "") + " " + page.text[:400].strip(),
                }
                image_keys.append(vid)
        if image_keys and self.s.use_visual_vector:
            try:
                for vid in image_keys:
                    rec = vis_records[vid]
                    vec = self.visual_emb.embed_image(rec["image_path"], rec.get("caption", ""))
                    self.visual_store.add(vec, key=vid)
            except service.ServiceError as e:
                raise DocumentError(f"visual embedding service unavailable: {e}") from e
        self._save_visual_records(vis_records)

        doc_id = title
        self.manifest[doc_id] = {
            "title": parsed.title,
            "source_name": path.name,
            "sha256": digest,
            "added": time.strftime("%Y-%m-%d %H:%M:%S"),
            "num_pages": len(pages),
            "num_chunks": len(chunks),
            "num_images": len(image_keys),
        }
        self.save_all()
        return {"status": "added", "title": parsed.title, "doc_id": doc_id,
                "chunks": len(chunks), "images": len(image_keys)}

    def remove_document(self, title: str) -> bool:
        """Remove a document's indexed content from every store."""
        doc_id = None
        info = self.find_by_title(title)
        if info is not None:
            doc_id = next((k for k, v in self.manifest.items()
                           if v.get("title") == title), None)
        if doc_id is None:
            return False

        chunk_ids = {cid for cid in (
            c.chunk_id for c in self.keyword.chunks.values() if c.document == doc_id
        ) if cid}
        # keyword: drop chunks & rebuild
        self.keyword.rebuild([c for c in self.keyword.chunks.values()
                              if c.document != doc_id])

        # text vectors by chunk_id
        self.text_store.remove_by_keys(chunk_ids)

        # visual records + vectors by vid prefix
        vis = self._load_visual_records()
        to_remove = {k for k in vis if k.startswith(doc_id + ":")}
        self.visual_store.remove_by_keys(to_remove)
        for k in to_remove:
            vis.pop(k, None)
        self._save_visual_records(vis)

        # delete parsed page images
        shutil.rmtree(self.s.data_dir / "parsed" / doc_id, ignore_errors=True)
        self.manifest.pop(doc_id, None)
        self.save_all()
        return True

    # ---- query + quiz ---------------------------------------------------
    def answer(self, question: str, topic: Optional[str] = None) -> tuple[Answer, dict]:
        result = self.retriever.retrieve(question, topic)
        try:
            ans = self.answers.generate(question, result.evidence)
        except GenerationError as e:
            ans = Answer(
                answer=f"Generation error: {e}", grounded=False,
                supports_sources=False, sources=[],
            )
        ans.latency_ms += result.latency_ms
        return ans, result.diagnostics

    def quiz(self, n: int = 3, topic: Optional[str] = None,
             overwrite: bool = True) -> list[QuizQuestion]:
        # retrieve broadly (text+visual) to ground the quiz
        broad = self.retriever.retrieve(topic or "", topic)
        if not broad.evidence:
            raise DocumentError("No course material is loaded to quiz from.")
        return self.quizzes.generate(broad.evidence, n=n, topic=topic)
