"""Unit tests for the NumPy vector store and BM25 keyword index (offline)."""
import numpy as np
import pytest

from course_assistant.indexing import CosineVectorStore, KeywordIndex
from course_assistant.types import TextChunk


def _store(tmp_path, dim=4):
    return CosineVectorStore(tmp_path / "vec.npy", dim=dim)


def test_vector_store_add_search_remove(tmp_path):
    s = _store(tmp_path, dim=4)
    s.add([1.0, 0.0, 0.0, 0.0], key="a")
    s.add([0.0, 1.0, 0.0, 0.0], key="b")
    res = s.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert res[0][0] == "a"
    s.remove_by_keys({"a"})
    res2 = s.search([1.0, 0.0, 0.0, 0.0], top_k=2)
    assert all(k != "a" for k, _ in res2)


def test_vector_store_persistence_roundtrip(tmp_path):
    s = _store(tmp_path, dim=4)
    s.add([1, 0, 0, 0], key="alpha")
    s.add([0, 1, 0, 0], key="beta")
    s.save()
    r = CosineVectorStore(tmp_path / "vec.npy")
    assert r.keys == ["alpha", "beta"]
    assert r.dim == 4
    assert r.search([1, 0, 0, 0], top_k=2)[0][0] == "alpha"


def test_vector_store_wipes(tmp_path):
    s = _store(tmp_path, dim=2)
    s.add([1, 0], key="x")
    s.wipe()
    assert s.keys == []
    assert s.search([1, 0]) == []


def _kw(tmp_path):
    return KeywordIndex(tmp_path / "kw")


def _mk(text, doc="d", page=1, cid=None):
    return TextChunk(text=text, document=doc, page=page, chunk_id=cid)


def test_keyword_build_search(tmp_path):
    k = _kw(tmp_path)
    k.rebuild([_mk("the quick brown fox jumps over the lazy dog", cid="x1"),
               _mk("machine learning models learn from labeled data", cid="x2")])
    hits = k.search("lazy dog", top_k=2)
    assert hits and hits[0][0] == "x1"


def test_keyword_remove_by_doc_rebuilds(tmp_path):
    k = _kw(tmp_path)
    k.rebuild([_mk("apples are fruits", doc="a", cid="c1"),
               _mk("pears are fruits", doc="a", cid="c2"),
               _mk("trains move on rails", doc="b", cid="c3")])
    removed = k.remove_by_doc("a")
    assert removed == {"c1", "c2"}
    hits = k.search("fruit", top_k=3)
    assert all(k == "c3" for k, _ in hits)
