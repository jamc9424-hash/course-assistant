from course_assistant.ingest import ingest_text
from course_assistant.models import QuizQuestion, SourceEvidence, validate_answer
from course_assistant.quiz import build_quiz, reveal_solution, score_quiz
from course_assistant.retrieval import HybridRetriever, KeywordIndex, LocalEmbeddingIndex


def test_ingest_preserves_source_location_and_visual_reference():
    chunks = ingest_text(
        "Week 1 slides\nDecision trees split data using features.\nA chart shows impurity decreasing.",
        document_name="slides.txt",
        section="Week 1",
        page_or_slide="slide 4",
        image_path="artifacts/slides/page-4.png",
    )

    assert len(chunks) == 1
    assert chunks[0].source.document == "slides.txt"
    assert chunks[0].source.page_or_slide == "slide 4"
    assert chunks[0].source.image_path == "artifacts/slides/page-4.png"
    assert "Decision trees" in chunks[0].text


def test_ingest_chunks_long_text_while_preserving_source_details():
    text = " ".join(f"Topic {index} explains an important course concept with supporting details." for index in range(30))

    chunks = ingest_text(text, "lecture.pdf", section="Week 2", page_or_slide="page 3", image_path="page-3.png")

    assert len(chunks) > 1
    assert all(chunk.source.document == "lecture.pdf" for chunk in chunks)
    assert all(chunk.source.page_or_slide == "page 3" for chunk in chunks)
    assert all(chunk.source.section == "Week 2" for chunk in chunks)
    assert all(chunk.source.image_path == "page-3.png" for chunk in chunks)
    assert all(chunk.source.excerpt == chunk.text for chunk in chunks)


def test_hybrid_retriever_fuses_keyword_text_and_visual_embedding_channels():
    text_chunk = ingest_text("Retrieval uses semantic text embeddings.", "notes.txt")[0]
    visual_chunk = ingest_text("A retrieval diagram connects query and evidence.", "slides.pdf", image_path="slide.png")[0]

    class Embeddings:
        def embed_text(self, texts):
            return [[1.0, 0.0]]

        def embed_visual(self, inputs):
            return [[0.0, 1.0]]

    from course_assistant.retrieval import VectorIndex

    retriever = HybridRetriever(
        text_index=KeywordIndex([text_chunk]),
        visual_index=KeywordIndex([visual_chunk]),
        text_vector_index=VectorIndex([text_chunk], [[1.0, 0.0]]),
        visual_vector_index=VectorIndex([visual_chunk], [[0.0, 1.0]]),
        embedding_client=Embeddings(),
    )

    results = retriever.search("retrieval diagram", top_k=2)

    assert len(results) == 2
    assert any("embedding" in result.channel for result in results)
    assert results[0].chunk.source.image_path == "slide.png"


def test_hybrid_retriever_uses_local_text_and_visual_embedding_indexes():
    text_chunk = ingest_text("Semantic retrieval connects a question to evidence.", "notes.txt")[0]
    visual_chunk = ingest_text("A visual chart compares evidence quality.", "slides.pdf", image_path="slide.png")[0]
    retriever = HybridRetriever(
        KeywordIndex([text_chunk]),
        KeywordIndex([visual_chunk]),
        LocalEmbeddingIndex.from_chunks([text_chunk]),
        LocalEmbeddingIndex.from_chunks([visual_chunk]),
    )

    results = retriever.search("semantic retrieval", top_k=2)

    assert results
    assert retriever.text_vector_index is not None
    assert retriever.visual_vector_index is not None
    assert any("embedding" in result.channel for result in results)


def test_hybrid_retriever_keeps_text_and_visual_indexes_separate():
    text_chunk = ingest_text("A syllabus defines the grading policy.", "syllabus.txt")[0]
    visual_chunk = ingest_text(
        "A chart shows impurity decreasing.",
        "slides.pdf",
        page_or_slide="page 2",
        image_path="artifacts/page-2.png",
    )[0]
    retriever = HybridRetriever(
        text_index=KeywordIndex([text_chunk]),
        visual_index=KeywordIndex([visual_chunk]),
    )

    result = retriever.search("What does the chart show?", top_k=2)

    assert result
    assert result[0].chunk.source.image_path == "artifacts/page-2.png"
    assert retriever.text_index is not retriever.visual_index


def test_answer_validation_rejects_sources_without_supporting_excerpt():
    source = SourceEvidence(
        document="notes.txt", section="Topic", excerpt="not in evidence"
    )

    try:
        validate_answer(
            answer="The material says this.",
            sources=[source],
            evidence_text_by_document={"notes.txt": "The material says something else."},
        )
    except ValueError as exc:
        assert "support" in str(exc).lower()
    else:
        raise AssertionError("unsupported evidence should be rejected")


def test_quiz_answer_key_is_fixed_and_solution_is_hidden_until_reveal():
    chunks = [
        ingest_text("A decision tree recursively splits data using features.", "slides.txt")[0],
        ingest_text("A syllabus lists office hours on Tuesday.", "syllabus.txt")[0],
    ]
    quiz = build_quiz(chunks, question_count=1, seed=7)
    key_before = quiz.questions[0].correct_choice

    assert quiz.questions[0].explanation is None
    assert score_quiz(quiz, {}) == {"score": 0, "total": 1, "answered": 0}
    assert "Which statement" not in quiz.questions[0].prompt
    revealed = reveal_solution(quiz, 0)
    assert revealed.correct_choice == key_before
    assert revealed.explanation
