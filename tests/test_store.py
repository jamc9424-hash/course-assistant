"""Offline tests for document management (add/remove/dedupe) and persistence.

These run without network or model services: vector embedding is disabled via
routing flags, so only parsing + the keyword index are exercised. The e2e test
file covers the full service-backed workflow (and skips if services are down).
"""
import pytest

from course_assistant import config
from course_assistant.store import CourseAssistant


def _assistant(tmp_path, vectors=False):
    s = config.Settings(
        data_dir=tmp_path / "data",
        api_key="unused-for-offline",
        vision_llm_url="http://127.0.0.1:5999",   # unreachable; not used here
        text_embedding_url="http://127.0.0.1:5999",
        visual_embedding_url="http://127.0.0.1:5999",
        rerank_url="http://127.0.0.1:5999",
        document_parser_url="http://127.0.0.1:5999",
        use_keyword=True,
        use_text_vector=vectors,
        use_visual_vector=vectors,
        use_rerank=False,
    )
    return CourseAssistant(s)


def _md(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_add_md_indexes_and_lists(tmp_path):
    helper = _assistant(tmp_path)
    src = _md(tmp_path, "week1.md", "Version control and git basics.\n" * 20)
    r = helper.add_file(src)
    assert r["status"] == "added"
    docs = helper.list_documents()
    assert any(d["title"] == "week1" for d in docs)


def test_duplicate_upload_ignored(tmp_path):
    helper = _assistant(tmp_path)
    src = _md(tmp_path, "notes.md", "same exact content repeated.\n" * 25)
    first = helper.add_file(src)
    second = helper.add_file(src)
    assert first["status"] == "added"
    assert second["status"] == "duplicate"
    docs = helper.list_documents()
    assert sum(1 for d in docs if d["title"] == "notes") == 1


def test_remove_drops_indexed_content(tmp_path):
    helper = _assistant(tmp_path)
    a = _md(tmp_path, "botany.md", "Photosynthesis happens in leaves. " * 20)
    b = _md(tmp_path, "astro.md", "Nebulae are vast clouds of gas. " * 20)
    helper.add_file(a)
    helper.add_file(b)
    assert len(helper.list_documents()) == 2
    assert helper.remove_document("botany") is True
    remaining = helper.list_documents()
    assert all(d["title"] != "botany" for d in remaining)
    # keyword index no longer contains any botany chunks or term hits
    assert all(c.document != "botany" for c in helper.keyword.chunks.values())
    hits = helper.keyword.search("photosynthesis", top_k=5)
    assert all(helper.keyword.chunks[cid].document != "botany" for cid, _ in hits)


def test_remove_nonexistent_returns_false(tmp_path):
    helper = _assistant(tmp_path)
    assert helper.remove_document("ghost") is False


def test_add_missing_file_raises(tmp_path):
    helper = _assistant(tmp_path)
    from course_assistant.store import DocumentError
    with pytest.raises(DocumentError):
        helper.add_file(tmp_path / "does-not-exist.pdf")


def test_persistence_across_reload(tmp_path):
    dir_a = _assistant(tmp_path)
    src = _md(tmp_path, "persist.md", "Persistence means data survives. " * 15)
    dir_a.add_file(src)
    dir_a.save_all()
    # reload a fresh assistant against the same data dir
    dir_b = _assistant(tmp_path)
    assert any(d["title"] == "persist" for d in dir_b.list_documents())
