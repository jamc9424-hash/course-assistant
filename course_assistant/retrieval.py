"""Hybrid retrieval: keyword + text-vector + visual-vector, RRF merge, rerank.

Produces a ranked list of *evidence items*. Each text hit maps to a chunk with
its source location; each visual hit maps to a page/slide image plus its OCR
caption (used both for display and for reranking).
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import Settings
from .indexing import CosineVectorStore, KeywordIndex
from .service import ServiceError, TextEmbeddingClient, VisualEmbeddingClient, RerankClient
from .types import SourceLocation, TextChunk, VisualRecord


def _encode_img(image_path: str) -> str:
    mime = "image/png"
    low = image_path.lower()
    if low.endswith(".jpg") or low.endswith(".jpeg"):
        mime = "image/jpeg"
    b64 = base64.b64encode(open(image_path, "rb").read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


@dataclass
class Evidence:
    kind: str                       # "text" | "visual"
    score: float
    chunk: Optional[TextChunk] = None
    visual: Optional[VisualRecord] = None
    source: Optional[SourceLocation] = None

    def __post_init__(self) -> None:
        if self.kind == "text" and self.chunk is not None:
            self.source = SourceLocation(
                document=self.chunk.document,
                page=self.chunk.page,
                section=self.chunk.section,
                excerpt=self.chunk.text[:400],
            )
        elif self.kind == "visual" and self.visual is not None:
            self.source = SourceLocation(
                document=self.visual.document,
                page=self.visual.page,
                section=self.visual.section,
                excerpt=(self.visual.caption or "")[:400],
                image_path=self.visual.image_path,
                image_mime=self.visual.image_mime,
            )


@dataclass
class RetrievalResult:
    evidence: list[Evidence]
    latency_ms: float
    diagnostics: dict[str, Any] = field(default_factory=dict)


class HybridRetriever:
    def __init__(
        self,
        settings: Settings,
        keyword: KeywordIndex,
        text_store: CosineVectorStore,
        visual_store: CosineVectorStore,
        text_emb: TextEmbeddingClient,
        visual_emb: VisualEmbeddingClient,
        rerank: Optional[RerankClient] = None,
    ):
        self.s = settings
        self.keyword = keyword
        self.text_store = text_store
        self.visual_store = visual_store
        self.text_emb = text_emb
        self.visual_emb = visual_emb
        self.rerank = rerank

    # ---- evidence mapping ----------------------------------------------
    def __chunk(self, cid: str, score: float) -> Evidence:
        return Evidence(kind="text", score=score, chunk=self.keyword.chunks.get(cid))

    def __textvec(self, key: str, score: float) -> Evidence:
        # key is the chunk_id itself (kept in sync across stores).
        return Evidence(kind="text", score=score, chunk=self.keyword.chunks.get(key))

    def __visual(self, key: str, score: float, visuals: dict[str, VisualRecord]) -> Evidence:
        vis = visuals.get(key)
        return Evidence(kind="visual", score=score, visual=vis)

    # ---- RRF merge -----------------------------------------------------
    def _rrf(self, rankings: list[list[tuple[str, float]]], k: int) -> list[tuple[str, float]]:
        from collections import defaultdict
        agg: dict[str, float] = defaultdict(float)
        for ranking in rankings:
            for rank, (key, _s) in enumerate(ranking):
                agg[key] += 1.0 / (k + rank + 1)
        return sorted(agg.items(), key=lambda kv: kv[1], reverse=True)

    def retrieve(self, query: str, topic: Optional[str] = None) -> RetrievalResult:
        t0 = time.time()
        diagnostics: dict[str, Any] = {}
        if topic:
            query = f"{topic} {query}"

        rankings: list[list[tuple[str, float]]] = []
        visual_records = self._current_visuals()          # dict key -> VisualRecord

        # 1) keyword
        if self.s.use_keyword and self.keyword.chunks:
            kw = self.keyword.search(query, self.s.keyword_top_k)
            kw = [(cid, sc) for (cid, sc) in kw if cid in self.keyword.chunks]
            rankings.append([(f"k:{cid}", sc) for cid, sc in kw])
            diagnostics["keyword_hits"] = len(kw)

        # 2) text vector
        if self.s.use_text_vector and self.text_store.keys:
            try:
                q_vec = self.text_emb.embed([query])[0]
                tv = self.text_store.search(q_vec, self.s.text_top_k)
                rankings.append([(f"t:{key}", sc) for key, sc in tv])
                diagnostics["textvec_hits"] = len(tv)
            except ServiceError as e:
                diagnostics["textvec_error"] = str(e)

        # 3) visual vector (embed text-first through the VL embedder)
        if self.s.use_visual_vector and self.visual_store.keys:
            try:
                vq_vec = self.visual_emb.embed_text(query)
                vv = self.visual_store.search(vq_vec, self.s.visual_top_k)
                rankings.append([(f"v:{key}", sc) for key, sc in vv])
                diagnostics["visual_hits"] = len(vv)
            except ServiceError as e:
                diagnostics["visual_error"] = str(e)

        # merge
        merged = self._rrf(rankings, self.s.rrf_k)
        evidence: list[Evidence] = []
        for key, score in merged:
            if key.startswith("k:"):
                ev = self.__chunk(key[2:], score)
            elif key.startswith("t:"):
                ev = self.__textvec(key[2:], score)
            elif key.startswith("v:"):
                ev = self.__visual(key[2:], score, visual_records)
            else:
                continue
            if ev.source is not None:
                evidence.append(ev)

        # rerank
        if self.s.use_rerank and self.rerank is not None and evidence:
            try:
                evidence = self._rerank(query, evidence)
                diagnostics["reranked"] = True
            except ServiceError as e:
                diagnostics["rerank_error"] = str(e)

        return RetrievalResult(evidence=evidence, latency_ms=(time.time() - t0) * 1000,
                               diagnostics=diagnostics)

    def _rerank(self, query: str, evidence: list[Evidence]) -> list[Evidence]:
        def to_doc(ev: Evidence) -> Any:
            if ev.kind == "visual" and ev.visual is not None and ev.visual.image_path:
                content = [
                    {"type": "image_url", "image_url": {"url": _encode_img(ev.visual.image_path)}},
                    {"type": "text", "text": ev.visual.caption or ""},
                ]
                return {"content": content}
            if ev.source is None:
                return ""
            return ev.source.excerpt or (ev.source.section or "")

        docs = [to_doc(e) for e in evidence]
        results = self.rerank.rerank(query, docs, top_n=self.s.rerank_top_n)
        ordered: list[Evidence] = []
        for r in results:
            idx = int(r["index"])
            if 0 <= idx < len(evidence):
                ev = evidence[idx]
                ev.score = float(r["relevance_score"])
                ordered.append(ev)
        return ordered or evidence

    def _current_visuals(self) -> dict[str, VisualRecord]:
        # records.json maps visual key -> VisualRecord payload.
        rec_path = self.visual_store.path.with_suffix(".records.json")
        if rec_path.is_file():
            import json
            data = json.loads(rec_path.read_text(encoding="utf-8"))
            return {k: VisualRecord(**item) for k, item in data.items()}
        return {}