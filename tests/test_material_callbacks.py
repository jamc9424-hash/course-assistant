from course_assistant.app import _add_files, _refresh_session, _remove_file, _score
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
    assert refreshed[11] == "{}"
