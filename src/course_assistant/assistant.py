from __future__ import annotations

from dataclasses import dataclass, replace
import re

from .models import AnswerResponse, DocumentChunk, SourceEvidence, validate_answer
from .quiz import build_quiz
from .services import ServiceReranker, image_path_to_data_url
from .retrieval import HybridRetriever, KeywordIndex, LocalEmbeddingIndex, _tokens, build_service_retriever


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
                retriever = HybridRetriever(
                    KeywordIndex(text_chunks),
                    KeywordIndex(visual_chunks),
                    LocalEmbeddingIndex.from_chunks(text_chunks) if text_chunks else None,
                    LocalEmbeddingIndex.from_chunks(visual_chunks) if visual_chunks else None,
                )
                service_client = None
        else:
            retriever = HybridRetriever(
                KeywordIndex(text_chunks),
                KeywordIndex(visual_chunks),
                LocalEmbeddingIndex.from_chunks(text_chunks) if text_chunks else None,
                LocalEmbeddingIndex.from_chunks(visual_chunks) if visual_chunks else None,
            )
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

    def _generate_grounded_answer(self, question: str, sources: list[SourceEvidence]) -> str | None:
        if not self.service_client:
            return None
        generator = getattr(self.service_client, "generate_answer", None)
        if generator is None:
            return None
        evidence = [
            {
                "document": source.document,
                "location": source.page_or_slide or source.section or "selected material",
                "excerpt": source.excerpt,
                "image_path": source.image_path,
            }
            for source in sources
        ]
        try:
            answer = generator(question, evidence)
            if not answer:
                return None
            answer_terms = set(_tokens(answer))
            evidence_terms = set(_tokens(" ".join(source.excerpt for source in sources)))
            return answer if answer_terms & evidence_terms else None
        except (OSError, RuntimeError, KeyError, IndexError, TypeError):
            return None

    def _local_grounded_answer(self, question: str, sources: list[SourceEvidence], visual_explanations: list[str]) -> str:
        query_terms = set(_tokens(question))
        ranked: list[tuple[int, str]] = []
        for source in sources:
            for sentence in re.split(r"(?<=[.!?])\s+", source.excerpt):
                sentence = sentence.strip()
                if sentence:
                    ranked.append((len(query_terms & set(_tokens(sentence))), sentence))
        ranked.sort(key=lambda item: item[0], reverse=True)
        selected: list[str] = []
        for overlap, sentence in ranked:
            if overlap or not selected:
                if sentence not in selected:
                    selected.append(sentence)
            if len(selected) >= 2:
                break
        answer = "The selected course materials support this answer: " + " ".join(selected)
        if visual_explanations:
            answer += "\n\nVisual evidence: " + " ".join(visual_explanations[:1])
        return answer

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
        query_terms = set(_tokens(question))
        evidence_terms = set(_tokens(" ".join(item.chunk.text for item in results)))
        required_overlap = 1 if len(query_terms) <= 2 or any(item.chunk.source.image_path for item in results) else 2
        if len(query_terms & evidence_terms) < required_overlap:
            return AnswerResponse("I could not find that information in the selected course materials.", ())
        matching_results = [
            item for item in results
            if query_terms & set(_tokens(item.chunk.text))
        ]
        results = (matching_results or results[:1])[:2]
        sources = []
        visual_explanations = []
        for item in results:
            source = item.chunk.source
            description = self._describe_visual(source)
            if description:
                source = replace(source, visual_description=description)
                visual_explanations.append(description)
            sources.append(source)
        answer = self._generate_grounded_answer(question, sources)
        if answer is None:
            answer = self._local_grounded_answer(question, sources, visual_explanations)
        evidence = {}
        for chunk in allowed:
            evidence[chunk.source.document] = evidence.get(chunk.source.document, "") + " " + chunk.text
        return validate_answer(answer, sources, evidence)

    def quiz(self, material: str | None = None, topic: str | None = None, question_count: int = 5, seed: int = 0):
        allowed = self._filtered_chunks(material, topic)
        if not allowed:
            raise ValueError("no course materials match the selection")
        return build_quiz(allowed, question_count=question_count, seed=seed)
