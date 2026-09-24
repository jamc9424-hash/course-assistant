"""Deterministic text chunking that preserves source metadata.

A small recursive character splitter (no heavy langchain dependency): each
chunk keeps its document, page, and section, so every retrieval hit is traceable
to a source location. Overlap avoids cutting through important sentences.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from .types import TextChunk

_SEP = re.compile(r"\s+")


def _clean(text: str) -> str:
    return " ".join(_SEP.split(text)).strip()


def split_text(
    text: str,
    chunk_size: int = 600,
    chunk_overlap: int = 120,
) -> list[str]:
    """Split text into overlapping chunks, hard-splitting long runs.

    Sentence-like boundaries (periods, !, ?, newlines) are preferred; a unit
    longer than ``chunk_size`` is additionally split on whitespace so chunking
    never produces an oversized chunk. Adjacent chunks share up to
    ``chunk_overlap`` characters' worth of words.
    """
    text = _clean(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    units = re.split(r"(?<=[.!?])\s+|\n+", text)
    units = [u.strip() for u in units if u.strip()]

    pieces: list[str] = []
    i = 0
    while i < len(units):
        chunk = units[i]
        i += 1
        while i < len(units) and len(chunk) + 1 + len(units[i]) <= chunk_size:
            chunk += " " + units[i]
            i += 1
        # hard-split if the accumulated chunk still exceeds the limit
        if len(chunk) > chunk_size:
            words = chunk.split()
            if len(words) == 1:
                pieces.append(chunk)   # a single unbreakable token
            else:
                head = words[0]
                w = 1
                while w < len(words) and len(head) + 1 + len(words[w]) <= chunk_size:
                    head += " " + words[w]
                    w += 1
                pieces.append(head)
                units.insert(i, " ".join(words[w:]))   # continue remaining words
        else:
            pieces.append(chunk)

    # add overlap across adjacent chunks
    result: list[str] = []
    for j, chunk in enumerate(pieces):
        if j > 0 and chunk_overlap > 0:
            overlap_toks, l = [], 0
            for t in reversed(pieces[j - 1].split()):
                if l + len(t) + 1 > chunk_overlap:
                    break
                overlap_toks.insert(0, t)
                l += len(t) + 1
            if overlap_toks:
                chunk = " ".join(overlap_toks) + " " + chunk
        result.append(chunk)
    return result


def chunk_pages(
    pages: list,
    document: str,
    chunk_size: int = 600,
    chunk_overlap: int = 120,
) -> list[TextChunk]:
    """Turn parsed pages into :class:`TextChunk` objects with provenance."""
    chunks: list[TextChunk] = []
    for page in pages:
        text = getattr(page, "text", "") or ""
        if not text.strip():
            continue
        parts = split_text(text, chunk_size, chunk_overlap)
        for part in parts:
            chunks.append(
                TextChunk(
                    text=part,
                    document=document,
                    page=page.index + 1,
                    section=getattr(page, "section", None),
                )
            )
    # dedupe identical (text, document) to keep the index clean
    seen: set[tuple] = set()
    out: list[TextChunk] = []
    for c in chunks:
        key = (c.document, c.page, c.text)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
