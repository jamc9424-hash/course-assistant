"""Tests for hybrid retrieval merge and evidence mapping (offline)."""
import pytest

from course_assistant.config import Settings
from course_assistant.retrieval import (HybridRetriever, _encode_img, Evidence)
from course_assistant.types import VisualRecord


class _Cfg:
    use_keyword = True
    use_text_vector = True
    use_visual_vector = True
    use_rerank = False
    rrf_k = 60
    keyword_top_k = 6
    text_top_k = 6
    visual_top_k = 4
    rerank_top_n = 6
    chunk_size = 300
    chunk_overlap = 60


def test_rrf_prefers_items_top_in_most_lists():
    r = HybridRetriever.__new__(HybridRetriever)  # don't run __init__
    rankings = [
        [("a", 1.0), ("b", 0.9)],
        [("a", 0.5), ("c", 0.4)],
        [("b", 0.2), ("c", 0.1)],
    ]
    merged = r._rrf(rankings, k=60)
    keys = [k for k, _ in merged]
    assert keys[0] == "a"   # appears #1 in two lists
    assert keys[1] == "b"   # appears in two lists


def test_rrf_scores_decrease_with_rank():
    r = HybridRetriever.__new__(HybridRetriever)
    merged = r._rrf([[(f"k{i}", float(i)) for i in range(5)]], k=60)
    scores = [s for _, s in merged]
    assert scores == sorted(scores, reverse=True)


def test_encode_img(tmp_path):
    import base64
    p = tmp_path / "x.png"
    p.write_bytes(b"\x89PNG-fake")
    enc = _encode_img(str(p))
    assert enc.startswith("data:image/png;base64,")
    assert base64.b64decode(enc.split(",", 1)[1]) == b"\x89PNG-fake"


def test_evidence_post_init_sets_source_from_visual(tmp_path):
    img = tmp_path / "slide.png"
    img.write_bytes(b"pngdata")
    vr = VisualRecord(document="deck", page=3, image_path=str(img), caption="ai fig")
    ev = Evidence(kind="visual", score=0.5, visual=vr)
    assert ev.source is not None
    assert ev.source.document == "deck"
    assert ev.source.page == 3
    assert ev.source.image_path == str(img)
