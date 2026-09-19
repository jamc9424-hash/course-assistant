from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .models import AnswerResponse, DocumentChunk, SourceEvidence, validate_answer
from .quiz import build_quiz
from .services import ServiceReranker, image_path_to_data_url
from .retrieval import HybridRetriever, KeywordIndex, build_service_retriever


@dataclass
class CourseAssistant:
    chunks: list[DocumentChunk]
    retriever: HybridRetriever
    service_client: object | None = None

    @classmethod
    def from_chunks(cls, chunks: list[DocumentChunk], service_client: object | None = None) -> "CourseAssistant":
        text_chunks = [chunk for chunk in chunks if chunk.text]
        visual_chunks = [chunk for chunk in chunks if chunk.source.image_path]
        if service_client:
            try:
                retriever = build_service_retriever(list(chunks), service_client)
                retriever.reranker = ServiceReranker(service_client)
            except RuntimeError:
                retriever = HybridRetriever(KeywordIndex(text_chunks), KeywordIndex(visual_chunks))
                service_client = None
        else:
            retriever = HybridRetriever(KeywordIndex(text_chunks), KeywordIndex(visual_chunks))
        return cls(chunks=list(chunks), retriever=retriever, service_client=service_client)

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

    def _describe_visual(self, source: SourceEvidence) -> str | None:
        if not self.service_client or not source.image_path:
            return None
        parser = getattr(self.service_client, "parse_image", None)
        if parser is None:
            return None
        instruction = (
            "Describe and explain the retrieved slide visual evidence. Identify relevant pictures, memes, "
            "diagrams, charts, labels, and relationships. Do not guess details that are not visible."
        )
        try:
            response = parser(image_path_to_data_url(source.image_path), instruction)
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if isinstance(content, list):
                content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
            return str(content).strip() or None
        except (OSError, RuntimeError, KeyError, IndexError, TypeError):
            return None

    def ask(self, question: str, material: str | None = None, topic: str | None = None) -> AnswerResponse:
        allowed = self._filtered_chunks(material, topic)
        if not allowed:
            return AnswerResponse("I could not find that information in the selected course materials.", ())
        try:
            scoped = CourseAssistant.from_chunks(allowed, service_client=self.service_client)
            results = scoped.retriever.search(question, top_k=3)
        except RuntimeError:
            # Degrade to the local keyword index if a remote service fails at ingest or query time.
            scoped = CourseAssistant.from_chunks(allowed)
            results = scoped.retriever.search(question, top_k=3)
        if not results:
            return AnswerResponse("I could not find that information in the selected course materials.", ())
        sources = []
        visual_explanations = []
        for item in results:
            source = item.chunk.source
            description = self._describe_visual(source)
            if description:
                source = replace(source, visual_description=description)
                visual_explanations.append(description)
            sources.append(source)
        answer = "Based on the selected course materials: " + " ".join(source.excerpt for source in sources)
        if visual_explanations:
            answer += " Visual evidence explanation: " + " ".join(visual_explanations)
        evidence = {}
        for chunk in allowed:
            evidence[chunk.source.document] = evidence.get(chunk.source.document, "") + " " + chunk.text
        return validate_answer(answer, sources, evidence)

    def quiz(self, material: str | None = None, topic: str | None = None, question_count: int = 5, seed: int = 0):
        allowed = self._filtered_chunks(material, topic)
        if not allowed:
            raise ValueError("no course materials match the selection")
        return build_quiz(allowed, question_count=question_count, seed=seed)
