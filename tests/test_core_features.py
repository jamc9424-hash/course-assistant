from course_assistant.ingest import ingest_text
from course_assistant.models import QuizQuestion, SourceEvidence, validate_answer
from course_assistant.quiz import build_quiz, reveal_solution, score_quiz
from course_assistant.retrieval import HybridRetriever, KeywordIndex


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
    revealed = reveal_solution(quiz, 0)
    assert revealed.correct_choice == key_before
    assert revealed.explanation
