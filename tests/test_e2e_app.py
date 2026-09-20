import json

import pytest

from course_assistant.app import _add_files, _answer, _quiz, _remove_file, _score
from course_assistant.materials import MaterialStore

pytestmark = pytest.mark.e2e


def test_complete_user_workflow_from_upload_to_removal(tmp_path):
    source = tmp_path / "course-notes.txt"
    source.write_text(
        "Decision trees recursively split data using features. "
        "Office hours are Tuesday at noon. "
        "The final project uses a held-out evaluation set.",
        encoding="utf-8",
    )
    store = MaterialStore(tmp_path / "artifacts")

    store, materials, upload_status = _add_files([str(source)], store)
    assert len(materials) == 1
    assert "added" in upload_status.casefold()
    document_id = materials[0]["document_id"]

    store, duplicate_materials, duplicate_status = _add_files([str(source)], store)
    assert len(duplicate_materials) == 1
    assert "duplicate" in duplicate_status.casefold()

    answer, images = _answer(store, "course-notes.txt", "", "When are office hours?")
    assert "Tuesday" in answer["answer"]
    assert answer["sources"][0]["document"] == "course-notes.txt"
    assert images == []

    quiz_json, quiz = _quiz(store, "course-notes.txt", "", 2)
    public_quiz = json.loads(quiz_json)
    assert quiz is not None
    assert len(public_quiz["questions"]) == 2
    assert all("correct_choice" not in item for item in public_quiz["questions"])

    first_question = quiz.questions[0]
    score_json = _score(
        quiz,
        json.dumps({first_question.question_id: first_question.correct_choice}),
        "",
    )
    feedback = json.loads(score_json)
    assert feedback["score"] == 1
    assert feedback["answered"] == 1
    assert len(feedback["feedback"]) == 1
    assert feedback["feedback"][0]["source"]["document"] == "course-notes.txt"

    store, remaining, removal_status = _remove_file(document_id, store)
    assert remaining == []
    assert "removed" in removal_status.casefold()

    missing_answer, missing_images = _answer(store, "", "", "When are office hours?")
    assert missing_images == []
    assert missing_answer["sources"] == []
    assert "could not find" in missing_answer["answer"].casefold()
