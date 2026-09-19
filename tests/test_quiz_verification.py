from course_assistant.ingest import ingest_text
from course_assistant.quiz import build_quiz, feedback_quiz, score_quiz


def _quiz():
    chunks = [
        ingest_text(
            "A decision tree recursively splits data using features. This helps create smaller groups.",
            "slides.pdf",
            page_or_slide="slide 4",
        )[0],
        ingest_text(
            "Office hours are Tuesday at noon.",
            "syllabus.pdf",
            page_or_slide="page 2",
        )[0],
    ]
    return build_quiz(chunks, question_count=2, seed=7)


def test_every_generated_correct_answer_is_supported_by_its_source():
    quiz = _quiz()

    for question in quiz.questions:
        correct = question.choices[question.correct_choice]
        assert correct in question.source.excerpt
        assert len(question.choices) >= 2
        assert question.source.document
        assert question.source.page_or_slide


def test_quiz_public_output_hides_solution_until_answered():
    quiz = _quiz()
    public = quiz.questions[0].public_dict()

    assert "correct_choice" not in public
    assert "explanation" not in public
    assert score_quiz(quiz, {}) == {"score": 0, "total": 2, "answered": 0}


def test_feedback_reveals_only_answered_questions_and_matches_key():
    quiz = _quiz()
    question = quiz.questions[0]
    feedback = feedback_quiz(quiz, {question.question_id: question.correct_choice})

    assert feedback["score"] == 1
    assert feedback["answered"] == 1
    assert len(feedback["feedback"]) == 1
    item = feedback["feedback"][0]
    assert item["correct"] is True
    assert item["correct_choice"] == question.correct_choice
    assert item["explanation"]
    assert item["source"]["document"] == question.source.document


def test_requested_solution_has_useful_explanation_and_source():
    quiz = _quiz()
    question = quiz.questions[0]
    feedback = feedback_quiz(quiz, {}, reveal_question_id=question.question_id)

    assert feedback["answered"] == 0
    assert feedback["feedback"][0]["question_id"] == question.question_id
    assert feedback["feedback"][0]["explanation"]
    assert feedback["feedback"][0]["source"]["page_or_slide"] == question.source.page_or_slide
