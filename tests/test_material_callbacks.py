from course_assistant.app import _add_files, _remove_file
from course_assistant.materials import MaterialStore


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
