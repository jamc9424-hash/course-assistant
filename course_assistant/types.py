"""Data types shared across the assistant (source records, chunks, answers)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SourceLocation:
    """A reproducible pointer to evidence inside a course document."""

    document: str
    page: Optional[int] = None          # page number (1-based) or slide number
    section: Optional[str] = None       # e.g. slide title / heading
    excerpt: Optional[str] = None       # short text snippet or OCR of the page
    image_path: Optional[str] = None    # path to the rendered page/slide PNG
    image_mime: str = "image/png"

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "page": self.page,
            "section": self.section,
            "excerpt": self.excerpt,
            "image_path": self.image_path,
            "image_mime": self.image_mime,
        }

    def summary(self) -> str:
        parts = [self.document]
        if self.page is not None:
            parts.append(f"page {self.page}")
        if self.section:
            parts.append(f"«{self.section}»")
        return " · ".join(parts)


@dataclass
class TextChunk:
    """A chunk of text with its provenance."""

    text: str
    document: str
    page: Optional[int] = None
    section: Optional[str] = None
    chunk_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "document": self.document,
            "page": self.page,
            "section": self.section,
            "chunk_id": self.chunk_id,
            "metadata": self.metadata,
        }


@dataclass
class VisualRecord:
    """A page/slide that exists as an image (for visual retrieval + display)."""

    document: str
    page: Optional[int] = None
    section: Optional[str] = None
    image_path: Optional[str] = None
    image_mime: str = "image/png"
    caption: Optional[str] = None   # first-line / OCR text, helpful for rerank

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "page": self.page,
            "section": self.section,
            "image_path": self.image_path,
            "image_mime": self.image_mime,
            "caption": self.caption,
        }


@dataclass
class Source:
    """A source reference attached to an answer or quiz explanation."""

    document: str
    page: Optional[int] = None
    section: Optional[str] = None
    excerpt: Optional[str] = None
    image_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "page": self.page,
            "section": self.section,
            "excerpt": self.excerpt,
            "image_path": self.image_path,
        }


@dataclass
class Answer:
    """Structured answer with separate answer/sources fields."""

    answer: str
    sources: list[Source] = field(default_factory=list)
    supports_sources: bool = True
    confidence: float = 0.0            # 0..1
    grounded: bool = True              # whether the materials support the answer
    note: Optional[str] = None         # e.g. "materials do not establish this"
    latency_ms: float = 0.0
    retrieval: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "grounded": self.grounded,
            "supports_sources": self.supports_sources,
            "confidence": self.confidence,
            "note": self.note,
            "latency_ms": self.latency_ms,
            "sources": [s.to_dict() for s in self.sources],
        }


@dataclass
class QuizQuestion:
    """A fixed-answer multiple-choice question."""

    question: str
    options: list[str]
    correct_index: int
    explanation: str
    sources: list[Source] = field(default_factory=list)
    id: Optional[str] = None

    def to_dict(self, reveal: bool = True) -> dict[str, Any]:
        d = {
            "id": self.id,
            "question": self.question,
            "options": self.options,
            "explanation": self.explanation,
            "sources": [s.to_dict() for s in self.sources],
        }
        if reveal:
            d["correct_index"] = self.correct_index
        return d
