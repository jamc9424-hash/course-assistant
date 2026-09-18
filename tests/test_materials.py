from pathlib import Path

from course_assistant.materials import MaterialStore


def test_uploading_same_file_twice_is_idempotent(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("Decision trees split data using features.", encoding="utf-8")
    store = MaterialStore(tmp_path / "artifacts")

    first = store.add_file(source)
    second = store.add_file(source)

    assert first.document_id == second.document_id
    assert store.document_ids() == [first.document_id]
    assert len(store.chunks()) == 1


def test_removing_document_removes_searchable_content_and_artifacts(tmp_path: Path):
    source = tmp_path / "notes.txt"
    source.write_text("Office hours are Tuesday at noon.", encoding="utf-8")
    store = MaterialStore(tmp_path / "artifacts")
    record = store.add_file(source)

    assert store.chunks()
    assert store.remove(record.document_id) is True
    assert store.chunks() == []
    assert store.document_ids() == []
    assert store.remove(record.document_id) is False
    assert store.remove("../../outside") is False


def test_unsupported_format_fails_without_partial_upload(tmp_path: Path):
    source = tmp_path / "notes.xyz"
    source.write_bytes(b"unsupported")
    store = MaterialStore(tmp_path / "artifacts")

    try:
        store.add_file(source)
    except ValueError as exc:
        assert "unsupported" in str(exc).casefold()
    else:
        raise AssertionError("unsupported format should fail")
    assert store.document_ids() == []
