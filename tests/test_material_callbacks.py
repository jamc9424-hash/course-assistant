from course_assistant.app import _add_files, _feedback_markdown, _quiz_markdown, _refresh_session, _remove_file, _score, _score_choices
from course_assistant.ingest import ingest_text
from course_assistant.materials import MaterialStore
from course_assistant.quiz import build_quiz


def test_app_upload_and_remove_callbacks_share_one_store(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("The exam covers retrieval.", encoding="utf-8")
    store = MaterialStore(tmp_path / "artifacts")

    store, choices, status = _add_files([str(source)], store)
    document_id = choices[0]["document_id"]
    assert "added" in status.casefold()
    assert store.document_ids() == [document_id]

    store, choices, status = _remove_file(document_id, store)
    assert "removed" in status.casefold()
    assert choices == []
    assert store.chunks() == []


def test_score_rejects_non_object_json_without_crashing():
    chunks = [
        ingest_text("Retrieval uses indexed evidence.", "notes.txt")[0],
        ingest_text("Sources identify the supporting document.", "notes.txt")[0],
    ]
    quiz = build_quiz(chunks, question_count=1)

    result = _score(quiz, "[]", "")

    assert '"error"' in result
    assert "JSON object" in result


def test_score_rejects_out_of_range_choice_and_feedback_shows_choice_text():
    quiz = build_quiz([
        ingest_text("Retrieval uses indexed evidence.", "notes.txt")[0],
        ingest_text("Sources identify the supporting document.", "notes.txt")[0],
    ], question_count=1)
    assert "error" in _score(quiz, '{"q1": 999}', "")
    assert "error" in _score(quiz, '{"stale": 0}', "")
    assert "Answered: **0 of 1**" in _score_choices(quiz, "", 999)
    result = _score_choices(quiz, "", quiz.questions[0].correct_choice)
    assert "Answered: **1 of 1**" in result
    assert quiz.questions[0].choices[quiz.questions[0].correct_choice] in result


def test_refresh_session_clears_materials_and_practice_state(tmp_path):
    old_store = MaterialStore(tmp_path / "artifacts")
    source = tmp_path / "notes.txt"
    source.write_text("Retrieval uses indexed evidence.", encoding="utf-8")
    _add_files([str(source)], old_store)

    refreshed = _refresh_session()

    assert isinstance(refreshed[0], MaterialStore)
    assert refreshed[0].chunks() == []
    assert refreshed[1] is None
    assert refreshed[2] == []
    assert refreshed[5] == ""
    assert refreshed[9] == ""
    assert refreshed[10] is None
    assert refreshed[11] == ""


def test_practice_materials_render_as_clean_markdown_without_solution_leakage():
    chunks = [
        ingest_text("Retrieval uses indexed evidence from course materials.", "notes.txt")[0],
        ingest_text("Sources identify the supporting document and location.", "notes.txt")[0],
    ]
    quiz = build_quiz(chunks, question_count=1)

    rendered = _quiz_markdown(quiz)
    feedback = _feedback_markdown({
        "score": 1,
        "total": 1,
        "answered": 1,
        "feedback": [{
            "question_id": "q1",
            "answered": True,
            "correct": True,
            "selected_choice": 0,
            "correct_choice": 0,
            "explanation": "The statement is supported by the material.",
            "source": {"document": "notes.txt", "page_or_slide": "page 1", "excerpt": "Retrieval uses indexed evidence from course materials."},
        }],
    })

    assert "## Practice test" in rendered
    assert "**A.**" in rendered
    assert "correct_choice" not in rendered
    assert "## Practice test results" in feedback
    assert "Score: **1 / 1**" in feedback
    assert "notes.txt" in feedback
