from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class SourceEvidence:
    document: str
    page_or_slide: str | None = None
    section: str | None = None
    excerpt: str = ""
    image_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "page_or_slide": self.page_or_slide,
            "section": self.section,
            "excerpt": self.excerpt,
            "image_path": self.image_path,
        }


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    text: str
    source: SourceEvidence
    modality: str = "text"


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: DocumentChunk
    score: float
    channel: str


@dataclass(frozen=True)
class AnswerResponse:
    answer: str
    sources: tuple[SourceEvidence, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"answer": self.answer, "sources": [s.as_dict() for s in self.sources]}


@dataclass(frozen=True)
class QuizQuestion:
    question_id: str
    prompt: str
    choices: tuple[str, ...]
    correct_choice: int
    source: SourceEvidence
    explanation: str | None = None

    def public_dict(self, reveal: bool = False) -> dict[str, Any]:
        data = {
            "question_id": self.question_id,
            "prompt": self.prompt,
            "choices": list(self.choices),
            "source": self.source.as_dict(),
        }
        if reveal:
            data["correct_choice"] = self.correct_choice
            data["explanation"] = self.explanation
        return data


@dataclass(frozen=True)
class Quiz:
    questions: tuple[QuizQuestion, ...]
    revealed: frozenset[str] = field(default_factory=frozenset)


def validate_answer(
    answer: str,
    sources: list[SourceEvidence] | tuple[SourceEvidence, ...],
    evidence_text_by_document: dict[str, str],
) -> AnswerResponse:
    if not answer.strip():
        raise ValueError("answer must not be empty")
    if not sources:
        raise ValueError("at least one supporting source is required")
    for source in sources:
        evidence = evidence_text_by_document.get(source.document, "")
        if not source.excerpt.strip() or source.excerpt.casefold() not in evidence.casefold():
            raise ValueError(f"source excerpt does not support answer: {source.document}")
    return AnswerResponse(answer=answer.strip(), sources=tuple(sources))


def reveal_question(question: QuizQuestion) -> QuizQuestion:
    if question.explanation:
        return question
    return replace(question, explanation=f"The selected course material supports: {question.choices[question.correct_choice]}")
