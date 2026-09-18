from __future__ import annotations

from dataclasses import dataclass

from .models import AnswerResponse, DocumentChunk, SourceEvidence, validate_answer
from .quiz import build_quiz
from .services import ServiceReranker
from .retrieval import HybridRetriever, KeywordIndex, build_service_retriever


@dataclass
class CourseAssistant:
    chunks: list[DocumentChunk]
    retriever: HybridRetriever

    @classmethod
    def from_chunks(cls, chunks: list[DocumentChunk], service_client: object | None = None) -> "CourseAssistant":
        text_chunks = [chunk for chunk in chunks if chunk.modality == "text"]
        visual_chunks = [chunk for chunk in chunks if chunk.modality == "visual"]
        if service_client:
            retriever = build_service_retriever(list(chunks), service_client)
            retriever.reranker = ServiceReranker(service_client)
        else:
            retriever = HybridRetriever(KeywordIndex(text_chunks), KeywordIndex(visual_chunks))
        return cls(chunks=list(chunks), retriever=retriever)

    def _filtered_chunks(self, material: str | None, topic: str | None) -> list[DocumentChunk]:
        result = self.chunks
        if material:
            result = [chunk for chunk in result if chunk.source.document == material]
        if topic:
            topic_folded = topic.casefold()
            result = [
                chunk for chunk in result
                if topic_folded in chunk.text.casefold()
                or topic_folded in (chunk.source.section or "").casefold()
            ]
        return result

    def ask(self, question: str, material: str | None = None, topic: str | None = None) -> AnswerResponse:
        allowed = self._filtered_chunks(material, topic)
        if not allowed:
            return AnswerResponse("I could not find that information in the selected course materials.", ())
        scoped = CourseAssistant.from_chunks(allowed)
        results = scoped.retriever.search(question, top_k=3)
        if not results:
            return AnswerResponse("I could not find that information in the selected course materials.", ())
        sources = [item.chunk.source for item in results]
        answer = "Based on the selected course materials: " + " ".join(source.excerpt for source in sources)
        evidence = {chunk.source.document: chunk.text for chunk in allowed}
        return validate_answer(answer, sources, evidence)

    def quiz(self, material: str | None = None, topic: str | None = None, question_count: int = 5, seed: int = 0):
        allowed = self._filtered_chunks(material, topic)
        if not allowed:
            raise ValueError("no course materials match the selection")
        return build_quiz(allowed, question_count=question_count, seed=seed)
