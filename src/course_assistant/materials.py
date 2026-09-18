from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .ingest import ingest_file
from .models import DocumentChunk

_SUPPORTED_SUFFIXES = {".pdf", ".pptx", ".docx", ".txt", ".md", ".markdown"}


@dataclass(frozen=True)
class MaterialRecord:
    document_id: str
    filename: str
    content_hash: str
    chunks: tuple[DocumentChunk, ...]


class MaterialStore:
    """Session-scoped material registry with content-addressed deduplication."""

    def __init__(self, artifact_root: str | Path = "artifacts"):
        self.artifact_root = Path(artifact_root)
        self._records: dict[str, MaterialRecord] = {}
        self._hash_to_id: dict[str, str] = {}

    def add_file(self, path: str | Path) -> MaterialRecord:
        file_path = Path(path)
        suffix = file_path.suffix.casefold()
        if suffix not in _SUPPORTED_SUFFIXES:
            raise ValueError(f"unsupported file format: {suffix or '(none)'}")
        if not file_path.is_file():
            raise FileNotFoundError(file_path)
        content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        existing_id = self._hash_to_id.get(content_hash)
        if existing_id:
            return self._records[existing_id]

        document_id = content_hash[:16]
        artifact_dir = self.artifact_root / document_id
        try:
            chunks = tuple(ingest_file(file_path, artifact_dir=artifact_dir))
        except Exception:
            if artifact_dir.exists():
                shutil.rmtree(artifact_dir)
            raise
        record = MaterialRecord(document_id, file_path.name, content_hash, chunks)
        self._records[document_id] = record
        self._hash_to_id[content_hash] = document_id
        return record

    def remove(self, document_id: str) -> bool:
        if not re.fullmatch(r"[0-9a-f]{16}", document_id or ""):
            return False
        record = self._records.pop(document_id, None)
        if record is None:
            return False
        self._hash_to_id.pop(record.content_hash, None)
        artifact_dir = self.artifact_root / document_id
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        return True

    def records(self) -> list[MaterialRecord]:
        return list(self._records.values())

    def document_ids(self) -> list[str]:
        return list(self._records)

    def chunks(self) -> list[DocumentChunk]:
        return [chunk for record in self._records.values() for chunk in record.chunks]

    def names(self) -> list[str]:
        return [record.filename for record in self._records.values()]
