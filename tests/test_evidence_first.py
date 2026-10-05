import pytest

from course_assistant.assistant import CourseAssistant
from course_assistant.ingest import ingest_text
from course_assistant.quiz import build_quiz, build_generated_quiz
from course_assistant.retrieval import KeywordIndex, VectorIndex, HybridRetriever


def test_vector_index_excludes_zero_and_negative_similarity():
    chunks = [ingest_text("Bananas are yellow.", "a.txt")[0], ingest_text("Rivers flow downhill.", "b.txt")[0]]
    index = VectorIndex(chunks, [[1.0, 0.0], [-1.0, 0.0]])
    assert index.search([0.0, 1.0]) == []
    assert [r.chunk.source.document for r in index.search([1.0, 0.0])] == ["a.txt"]


def test_hybrid_ignores_unrelated_visual_vector_hit():
    chunk = ingest_text("Bananas are yellow.", "a.txt", image_path="banana.png")[0]
    retriever = HybridRetriever(KeywordIndex([]), KeywordIndex([chunk]), visual_vector_index=VectorIndex([chunk], [[0.0, 1.0]]))
    assert retriever.search("river") == []


def test_reranker_batches_candidates_and_falls_back_on_invalid_scores():
    chunks = [ingest_text("Decision trees split records.", "a.txt")[0],
              ingest_text("Decision trees use feature thresholds.", "b.txt")[0]]

    class Reranker:
        calls = 0

        def score_many(self, query, candidates):
            self.calls += 1
            assert len(candidates) == 2
            return []

    reranker = Reranker()
    index = HybridRetriever(KeywordIndex(chunks), KeywordIndex([]), reranker=reranker)
    result = index.search("decision trees", top_k=2)
    assert len(result) == 2
    assert reranker.calls == 1


def test_reranker_encodes_image_instead_of_sending_local_path(tmp_path):
    from course_assistant.services import ServiceReranker
    image = tmp_path / "slide.png"
    image.write_bytes(b"image")
    chunk = ingest_text("Decision tree diagram.", "slide.pdf", image_path=str(image))[0]

    class Fake:
        def rerank(self, query, documents):
            assert documents[0]["image"].startswith("data:image/png;base64,")
            assert str(image) not in str(documents)
            return [0.8]

    assert ServiceReranker(Fake()).score_many("diagram", [chunk]) == [0.8]


def test_model_answer_requires_valid_citation_to_evidence():
    class Fake:
        def embed_text(self, texts):
            raise RuntimeError("offline")

        def generate_answer(self, question, evidence):
            return "The exam is worth 70 percent [99]."

    chunks = ingest_text("Office hours are Tuesday at noon.", "syllabus.txt")
    response = CourseAssistant.from_chunks(chunks, Fake()).ask("When are office hours?")
    assert "70 percent" not in response.answer
    assert "Tuesday" in response.answer


def test_quiz_uses_exact_statement_completion_not_other_true_facts():
    chunks = [
        *ingest_text("Decision trees split data using features. Gradient descent minimizes a loss function.", "notes.txt"),
        *ingest_text("The syllabus lists office hours on Tuesday. Cross validation estimates generalization error.", "week1.txt"),
    ]
    quiz = build_quiz(chunks, question_count=2, seed=3)
    assert len(quiz.questions) == 2
    for question in quiz.questions:
        assert "complete" in question.prompt.casefold()
        assert "___" in question.prompt
        assert question.choices[question.correct_choice] in question.source.excerpt
        assert question.source.excerpt.count(".") <= 1
        assert question.prompt.casefold().count("which statement") == 0
        assert len(question.choices) >= 3


def test_quiz_refuses_unreliable_source_instead_of_guessing():
    chunks = ingest_text("[Visual page with no extractable text]", "slide.pdf")
    with pytest.raises(ValueError, match="usable|extractable|statement"):
        build_quiz(chunks, question_count=1)


def test_generated_concept_question_is_anchored_and_key_hidden():
    chunks = ingest_text("Decision trees split records using feature thresholds.", "notes.txt", page_or_slide="page 2")
    item = lambda text, image_path=None: {
        "prompt": "What do decision trees use to split records?",
        "correct": "feature thresholds",
        "distractors": ["random labels", "calendar dates", "student names"],
        "explanation": "The source states that trees split records using feature thresholds.",
    }
    quiz = build_generated_quiz(chunks, item, question_count=1)
    assert quiz.questions[0].choices[quiz.questions[0].correct_choice] == "feature thresholds"
    assert quiz.questions[0].source.page_or_slide == "page 2"
    assert "correct_choice" not in quiz.questions[0].public_dict()


def test_generated_quiz_rejects_unanchored_correct_answer_and_duplicate_choices():
    chunks = ingest_text("Decision trees split records using feature thresholds.", "notes.txt")
    with pytest.raises(ValueError, match="verifiable"):
        build_generated_quiz(chunks, lambda text, image_path=None: {
            "prompt": "What do decision trees use?", "correct": "moonlight",
            "distractors": ["a", "b", "c"], "explanation": "Trust me."
        })
    with pytest.raises(ValueError, match="verifiable"):
        build_generated_quiz(chunks, lambda text, image_path=None: {
            "prompt": "What do decision trees use?", "correct": "feature thresholds",
            "distractors": ["feature thresholds", "b", "c"], "explanation": "Trust me."
        })


def test_assistant_prefers_concept_quiz_when_service_available():
    class Fake:
        def embed_text(self, texts):
            raise RuntimeError("offline embeddings")

        def generate_quiz_item(self, evidence, image_path=None):
            return {
                "prompt": "What do decision trees use to split records?", "correct": "feature thresholds",
                "distractors": ["random labels", "calendar dates", "student names"],
                "explanation": "The source states that trees split records using feature thresholds.",
            }

    chunks = ingest_text("Decision trees split records using feature thresholds.", "notes.txt")
    quiz = CourseAssistant.from_chunks(chunks, Fake()).quiz(question_count=1)
    assert "What do decision trees" in quiz.questions[0].prompt


def test_related_topic_without_requested_deadline_abstains():
    chunks = ingest_text("The final project uses a held-out evaluation set.", "notes.txt")
    response = CourseAssistant.from_chunks(chunks).ask("What is the final project deadline?")
    assert response.sources == ()
    assert "could not find" in response.answer


def test_cancelled_office_hours_are_not_inferred_from_schedule():
    chunks = ingest_text("Office hours are Tuesday at noon.", "notes.txt")
    response = CourseAssistant.from_chunks(chunks).ask("Are office hours cancelled?")
    assert response.sources == ()


def test_deadline_for_different_subject_in_same_chunk_is_not_reused():
    text = "The final project uses a held-out evaluation set. The weekly quiz deadline is Friday."
    response = CourseAssistant.from_chunks(ingest_text(text, "notes.txt")).ask("What is the final project deadline?")
    assert response.sources == ()


def test_model_cannot_add_unsupported_nonnumeric_claim():
    class Fake:
        def embed_text(self, texts):
            raise RuntimeError("offline")

        def generate_answer(self, question, evidence):
            return "Office hours are Tuesday but attendance is mandatory [1]."

    chunks = ingest_text("Office hours are Tuesday at noon.", "notes.txt")
    answer = CourseAssistant.from_chunks(chunks, Fake()).ask("When are office hours?")
    assert "mandatory" not in answer.answer


def test_scanned_visual_page_uses_remote_visual_retrieval_and_cites_image(tmp_path):
    image = tmp_path / "page.png"
    image.write_bytes(b"image data for mocked service")

    class FakeVisual:
        def embed_text(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def embed_visual(self, inputs):
            return [[1.0, 0.0] for _ in inputs]

        def rerank(self, query, documents):
            return [1.0] * len(documents)

        def parse_image(self, image_data_url, instruction):
            return {"choices": [{"message": {"content": "The chart compares batch and stream processing."}}]}

        def generate_answer(self, question, evidence):
            assert evidence[0]["image_path"] == str(image)
            return "The chart compares batch and stream processing [1]."

    chunks = ingest_text("[Visual page with no extractable text]", "scan.pdf", page_or_slide="page 3", image_path=str(image))
    answer = CourseAssistant.from_chunks(chunks, FakeVisual()).ask("What does the chart compare?")
    assert "batch and stream processing" in answer.answer
    assert answer.sources[0].page_or_slide == "page 3"


def test_scanned_visual_page_offline_refuses_without_guessing(tmp_path):
    image = tmp_path / "page.png"
    image.write_bytes(b"image data")
    chunks = ingest_text("[Visual page with no extractable text]", "scan.pdf", image_path=str(image))
    answer = CourseAssistant.from_chunks(chunks).ask("What does the chart compare?")
    assert answer.sources == ()


def test_model_citation_numbers_stay_aligned_after_source_filtering():
    class Fake:
        def embed_text(self, texts):
            raise RuntimeError("offline")

        def generate_answer(self, question, evidence):
            assert evidence[1]["document"] == "office.txt"
            return "Office hours are Tuesday [2]."

    chunks = [ingest_text("Tuesday is a weekday in the calendar.", "calendar.txt")[0],
              ingest_text("Office hours are Tuesday at noon.", "office.txt")[0]]
    # Supply the evidence order directly: candidate retrieval ordering is an independent concern.
    assistant = CourseAssistant.from_chunks(chunks, Fake())
    sources = [chunk.source for chunk in chunks]
    assert assistant._generate_grounded_answer("office hours", sources) == "Office hours are Tuesday [2]."
    answer = assistant.ask("When are office hours?")
    assert len(answer.sources) == 1
    assert answer.sources[0].document == "office.txt"
    assert "[1]" in answer.answer
