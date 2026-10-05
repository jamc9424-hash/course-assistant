from __future__ import annotations

import base64
import hashlib
import math
import mimetypes
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .models import DocumentChunk, RetrievedChunk

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_STOPWORDS = {"a", "an", "the", "does", "do", "is", "are", "what", "how", "of", "to", "in", "and"}


def _tokens(value: str) -> list[str]:
    return [
        token.casefold()
        for token in _TOKEN_RE.findall(value)
        if token.casefold() not in _STOPWORDS
    ]


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


class Reranker(Protocol):
    def score(self, query: str, chunk: DocumentChunk) -> float: ...


class KeywordIndex:
    """Small dependency-free BM25-style index used as the reliable baseline."""

    def __init__(self, chunks: list[DocumentChunk]):
        self.chunks = list(chunks)
        self.term_frequencies = [Counter(_tokens(chunk.text)) for chunk in self.chunks]
        self.document_frequency = Counter(
            term for frequencies in self.term_frequencies for term in frequencies
        )
        self.average_length = (
            sum(sum(f.values()) for f in self.term_frequencies) / len(self.chunks)
            if self.chunks
            else 0.0
        )

    def search(self, query: str, top_k: int = 8) -> list[RetrievedChunk]:
        query_terms = _tokens(query)
        if not query_terms or not self.chunks:
            return []
        total = len(self.chunks)
        results: list[RetrievedChunk] = []
        for index, (chunk, frequencies) in enumerate(zip(self.chunks, self.term_frequencies)):
            length = sum(frequencies.values()) or 1
            score = 0.0
            for term in query_terms:
                tf = frequencies.get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (total - self.document_frequency[term] + 0.5) / (self.document_frequency[term] + 0.5))
                score += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * length / max(self.average_length, 1)))
            if score > 0:
                results.append(RetrievedChunk(chunk=chunk, score=score, channel="keyword"))
        return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]


def _image_input(path: str | None) -> str | None:
    if not path:
        return None
    image_path = Path(path)
    if not image_path.is_file():
        return None
    media_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


class VectorIndex:
    def __init__(self, chunks: list[DocumentChunk], vectors: list[list[float]]):
        if len(chunks) != len(vectors):
            raise ValueError("each chunk must have one embedding")
        self.chunks = list(chunks)
        self.vectors = list(vectors)

    def search(self, query_vector: list[float], top_k: int = 8) -> list[RetrievedChunk]:
        ranked = [
            RetrievedChunk(chunk, _cosine(query_vector, vector), "embedding")
            for chunk, vector in zip(self.chunks, self.vectors)
        ]
        return sorted(ranked, key=lambda item: item.score, reverse=True)[:top_k]


class LocalEmbeddingIndex(VectorIndex):
    """Dependency-free semantic fallback using deterministic token/ngram vectors."""

    DIMENSIONS = 256

    @classmethod
    def embed(cls, text: str) -> list[float]:
        vector = [0.0] * cls.DIMENSIONS
        tokens = _tokens(text)
        features = tokens + [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
        for feature in features:
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % cls.DIMENSIONS
            vector[index] += 1.0
        return vector

    @classmethod
    def from_chunks(cls, chunks: list[DocumentChunk]) -> "LocalEmbeddingIndex":
        return cls(chunks, [cls.embed(chunk.text) for chunk in chunks])


@dataclass
class HybridRetriever:
    text_index: KeywordIndex
    visual_index: KeywordIndex
    text_vector_index: VectorIndex | None = None
    visual_vector_index: VectorIndex | None = None
    embedding_client: object | None = None
    reranker: Reranker | None = None

    def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        """Recall from separate channels, fuse ranks, then rerank the candidates."""
        channel_results: list[list[RetrievedChunk]] = [
            self.text_index.search(query, top_k * 3),
            self.visual_index.search(query, top_k * 3),
        ]
        if self.text_vector_index:
            if self.embedding_client:
                query_vector = self.embedding_client.embed_text([f"query: {query}"])[0]
            else:
                query_vector = LocalEmbeddingIndex.embed(query)
            channel_results.append(self.text_vector_index.search(query_vector, top_k * 3))
            if self.visual_vector_index:
                if self.embedding_client:
                    visual_query_vector = self.embedding_client.embed_visual([{"text": query}])[0]
                else:
                    visual_query_vector = LocalEmbeddingIndex.embed(query)
                channel_results.append(self.visual_vector_index.search(visual_query_vector, top_k * 3))

        fused: dict[str, tuple[DocumentChunk, float, list[str]]] = {}
        for results in channel_results:
            for rank, item in enumerate(results, start=1):
                previous = fused.get(item.chunk.chunk_id)
                contribution = 1.0 / (60.0 + rank)
                if previous is None:
                    fused[item.chunk.chunk_id] = (item.chunk, contribution, [item.channel])
                else:
                    chunk, score, channels = previous
                    fused[item.chunk.chunk_id] = (
                        chunk,
                        score + contribution,
                        channels + ([item.channel] if item.channel not in channels else []),
                    )
        merged = [
            RetrievedChunk(chunk, score, "+".join(channels))
            for chunk, score, channels in fused.values()
        ]
        if self.reranker:
            reranked = [(self.reranker.score(query, item.chunk), item) for item in merged]
            reranked.sort(key=lambda pair: (pair[0], pair[1].score), reverse=True)
            return [item for _, item in reranked[:top_k]]
        return sorted(
            merged,
            key=lambda item: (item.score, bool(item.chunk.source.image_path)),
            reverse=True,
        )[:top_k]


def build_service_retriever(chunks: list[DocumentChunk], client: object) -> HybridRetriever:
    # Keep text in the text index even when a chunk also has a visual artifact.
    text_chunks = [chunk for chunk in chunks if chunk.text]
    visual_chunks = [chunk for chunk in chunks if chunk.source.image_path]
    text_vectors = client.embed_text([f"passage: {chunk.text}" for chunk in text_chunks]) if text_chunks else []
    visual_inputs = []
    for chunk in visual_chunks:
        item = {"text": chunk.text}
        image = _image_input(chunk.source.image_path)
        if image:
            item["image"] = image
        visual_inputs.append(item)
    visual_vectors = client.embed_visual(visual_inputs) if visual_inputs else []
    return HybridRetriever(
        KeywordIndex(text_chunks),
        KeywordIndex(visual_chunks),
        VectorIndex(text_chunks, text_vectors) if text_vectors else None,
        VectorIndex(visual_chunks, visual_vectors) if visual_vectors else None,
        embedding_client=client,
    )
