from __future__ import annotations

from dataclasses import dataclass, replace
import re

from .models import AnswerResponse, DocumentChunk, SourceEvidence, validate_answer
from .quiz import build_quiz, build_generated_quiz
from .services import ServiceReranker, image_path_to_data_url
from .retrieval import HybridRetriever, KeywordIndex, LocalEmbeddingIndex, _tokens, build_service_retriever

_FACT_INTENTS = {
    "deadline": ("deadline", "due", "date", "submit by"),
    "weight": ("weight", "percent", "percentage", "%", "worth"),
    "cost": ("cost", "price", "fee", "$"),
    "cancellation": ("cancelled", "canceled", "cancellation", "postponed"),
}


def _missing_requested_fact(question: str, evidence: str) -> bool:
    q, text = question.casefold(), evidence.casefold()
    return any(
        any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", q) for term in terms)
        and not any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in terms)
        for terms in _FACT_INTENTS.values()
    )


def _evidence_sentence(question: str, text: str) -> str | None:
    """Select a coherent sentence matching both subject and requested fact type."""
    terms = set(_tokens(question))
    intent_groups = [group for group in _FACT_INTENTS.values() if any(
        re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", question, re.I) for word in group
    )]
    subject_terms = terms - {word for group in intent_groups for word in group}
    candidates = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        overlap = len(terms & set(_tokens(sentence)))
        if not overlap:
            continue
        if intent_groups and subject_terms and len(subject_terms & set(_tokens(sentence))) < min(2, len(subject_terms)):
            continue
        if any(not any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", sentence, re.I)
                       for word in group) for group in intent_groups):
            continue
        candidates.append((overlap, sentence))
    return max(candidates, key=lambda pair: pair[0])[1] if candidates else None


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
                # Keep the client so 9001 answer generation and 9005 visual parsing
                # remain available when an optional embedding service is down.
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
            citations = [int(number) for number in re.findall(r"\[(\d+)\]", answer)]
            # A shared word is not evidence of entailment. Require explicit,
            # in-range provenance; otherwise use the extractive fallback.
            if not citations or any(number < 1 or number > len(sources) for number in citations):
                return None
            supported = " ".join(
                sources[number - 1].excerpt + " " + (sources[number - 1].visual_description or "")
                for number in set(citations)
            )
            answer_terms = set(_tokens(re.sub(r"\[\d+\]", "", answer)))
            supported_terms = set(_tokens(supported))
            if not answer_terms & supported_terms:
                return None
            # This is deliberately conservative. A cited source plus one
            # shared keyword cannot license a new factual assertion.
            if answer_terms - supported_terms - {"according", "source", "material", "means", "because", "therefore", "this", "that", "it"}:
                return None
            # Numerical claims (deadlines, amounts, weights) cannot be
            # licensed by citing an unrelated sentence.
            numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", answer)) - set(map(str, citations))
            if numbers - set(re.findall(r"\b\d+(?:\.\d+)?\b", supported)):
                return None
            return answer
        except (OSError, RuntimeError, KeyError, IndexError, TypeError):
            return None

    def _local_grounded_answer(self, question: str, sources: list[SourceEvidence], visual_explanations: list[str]) -> tuple[str, list[SourceEvidence]]:
        query_terms = set(_tokens(question))
        ranked: list[tuple[int, str, SourceEvidence]] = []
        for source in sources:
            for sentence in re.split(r"(?<=[.!?])\s+", source.excerpt):
                sentence = sentence.strip()
                if sentence:
                    ranked.append((len(query_terms & set(_tokens(sentence))), sentence, source))
        ranked.sort(key=lambda item: item[0], reverse=True)
        selected: list[tuple[str, SourceEvidence]] = []
        for overlap, sentence, source in ranked:
            if overlap and sentence not in [value for value, _ in selected] and not sentence.startswith("[Visual page"):
                selected.append((sentence, replace(source, excerpt=sentence)))
            if len(selected) >= 2:
                break
        if not selected:
            return "I could not find that information in the selected course materials.", []
        answer = "From the course material: " + " ".join(
            f"{sentence} [{index}]" for index, (sentence, _) in enumerate(selected, 1)
        )
        if visual_explanations:
            answer += "\n\nVisual description (model-generated; check the original image): " + visual_explanations[0]
        return answer, [source for _, source in selected]

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
        required_overlap = 1 if len(query_terms) <= 2 else 2
        visual_query = bool(re.search(r"\b(image|picture|diagram|chart|figure|visual|slide|meme)\b", question, re.I))
        # Scanned visual-only pages have no searchable extracted terms. Allow
        # the *remote* visual index to propose them, but never fabricate an
        # offline answer from the placeholder text.
        visual_only = bool(
            visual_query and scoped.retriever.embedding_client is not None
            and any(item.chunk.source.image_path and "embedding" in item.channel for item in results)
        )
        if len(query_terms & evidence_terms) < required_overlap and not visual_only:
            return AnswerResponse("I could not find that information in the selected course materials.", ())
        if _missing_requested_fact(question, " ".join(item.chunk.text for item in results)) and not visual_only:
            return AnswerResponse("I could not find that information in the selected course materials.", ())
        matching_results = [
            item for item in results
            if query_terms & set(_tokens(item.chunk.text))
        ]
        results = (results if visual_only else matching_results or results[:1])[:4]
        sources = []
        visual_explanations = []
        for item in results:
            source = item.chunk.source
            if not visual_only:
                sentence = _evidence_sentence(question, item.chunk.text)
                if not sentence:
                    continue
                source = replace(source, excerpt=sentence)
            description = self._describe_visual(source)
            if description:
                source = replace(source, visual_description=description)
                visual_explanations.append(description)
            sources.append(source)
        if not sources:
            return AnswerResponse("I could not find that information in the selected course materials.", ())
        answer = self._generate_grounded_answer(question, sources)
        if answer is None:
            answer, sources = self._local_grounded_answer(question, sources, visual_explanations)
        else:
            cited = {int(number) for number in re.findall(r"\[(\d+)\]", answer)}
            positions = {original: new for new, original in enumerate(sorted(cited), 1)}
            answer = re.sub(r"\[(\d+)\]", lambda match: f"[{positions[int(match.group(1))]}]", answer)
            sources = [source for index, source in enumerate(sources, 1) if index in cited]
        if answer.startswith("I could not find"):
            return AnswerResponse(answer, ())
        evidence = {}
        for chunk in allowed:
            evidence[chunk.source.document] = evidence.get(chunk.source.document, "") + " " + chunk.text
        return validate_answer(answer, sources, evidence)

    def quiz(self, material: str | None = None, topic: str | None = None, question_count: int = 5, seed: int = 0):
        allowed = self._filtered_chunks(material, topic)
        if not allowed:
            raise ValueError("no course materials match the selection")
        generate = getattr(self.service_client, "generate_quiz_item", None)
        if generate:
            try:
                return build_generated_quiz(allowed, generate, question_count, seed)
            except ValueError:
                pass  # Service unavailable or invalid response: exact-source exercises only.
        return build_quiz(allowed, question_count=question_count, seed=seed)
