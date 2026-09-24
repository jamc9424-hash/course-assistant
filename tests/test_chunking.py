"""Unit tests for text chunking."""
import pytest

from course_assistant.chunking import chunk_pages, split_text
from course_assistant.parsing import Page


def test_split_text_small_input_is_single_chunk():
    assert split_text("short") == ["short"]


def test_split_respects_chunk_size():
    text = ("word " * 500).strip()  # ~2500 chars
    chunks = split_text(text, chunk_size=400, chunk_overlap=0)
    assert len(chunks) >= 4
    assert all(len(c) <= 410 for c in chunks)
    # reconstituted tokens appear somewhere
    joined = " ".join(chunks)
    assert "word" in joined


def test_split_with_overlap_shares_content_across_boundary():
    text = ("0123456789 " * 200).strip()
    chunks = split_text(text, chunk_size=200, chunk_overlap=60)
    for a, b in zip(chunks, chunks[1:]):
        # overlap implies some shared word
        assert set(a.split()) & set(b.split())


def test_empty_and_whitespace():
    assert split_text("") == []
    assert split_text("   \n\t  ") == []


def test_chunk_pages_preserve_provenance():
    pages = [
        Page(text="Alpha beta gamma delta epsilon zeta.", index=0, section="Intro"),
        Page(text="Eta theta iota kappa.", index=1, section="Body"),
        Page(text="", index=2, section=None),  # empty page skipped
    ]
    chunks = chunk_pages(pages, document="notes", chunk_size=200, chunk_overlap=0)
    assert chunks, "expected non-empty chunks"
    assert all(c.document == "notes" for c in chunks)
    for c in chunks:
        assert c.page in (1, 2)
    # provenance for intro content
    intro = [c for c in chunks if c.page == 1]
    assert intro and intro[0].section == "Intro"
