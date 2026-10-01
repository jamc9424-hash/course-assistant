from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

from .models import DocumentChunk, SourceEvidence

_MAX_INGEST_BYTES = 150 * 1024 * 1024
_MAX_RENDERED_PAGES = 500


def _chunk_id(document_name: str, location: str | None, text: str) -> str:
    raw = f"{document_name}|{location or ''}|{text}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def ingest_text(
    text: str,
    document_name: str,
    section: str | None = None,
    page_or_slide: str | None = None,
    image_path: str | None = None,
) -> list[DocumentChunk]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    source = SourceEvidence(
        document=document_name,
        page_or_slide=page_or_slide,
        section=section,
        excerpt=cleaned,
        image_path=image_path,
    )
    return [
        DocumentChunk(
            chunk_id=_chunk_id(document_name, page_or_slide, cleaned),
            text=cleaned,
            source=source,
            modality="visual" if image_path else "text",
        )
    ]


def ingest_file(path: str | Path, artifact_dir: str | Path = "artifacts") -> list[DocumentChunk]:
    """Parse a supported course file while retaining page/slide evidence when available."""
    file_path = Path(path)
    suffix = file_path.suffix.casefold()
    if file_path.is_file() and file_path.stat().st_size > _MAX_INGEST_BYTES:
        raise ValueError("course material exceeds the 150 MB upload limit")
    if suffix in {".txt", ".md", ".markdown"}:
        return ingest_text(file_path.read_text(encoding="utf-8"), file_path.name)
    if suffix == ".pdf":
        return _ingest_pdf(file_path, Path(artifact_dir))
    if suffix in {".pptx", ".ppt", ".odp"}:
        return _ingest_presentation(file_path, Path(artifact_dir))
    if suffix == ".docx":
        return _ingest_docx(file_path)
    raise ValueError(f"unsupported file format: {suffix or '(none)'}")


def _ingest_pdf(
    path: Path,
    artifact_dir: Path,
    location_prefix: str = "page",
    document_name: str | None = None,
) -> list[DocumentChunk]:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PDF support requires PyMuPDF; install the optional dependencies") from exc
    document = fitz.open(path)
    if document.page_count > _MAX_RENDERED_PAGES:
        document.close()
        raise ValueError("course material exceeds the 500-page rendering limit")
    chunks: list[DocumentChunk] = []
    output_dir = artifact_dir / path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        for page_index, page in enumerate(document, start=1):
            image_path = output_dir / f"page-{page_index}.png"
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pixmap.save(image_path)
            page_text = page.get_text("text").strip() or "[Visual page with no extractable text]"
            chunks.extend(
                ingest_text(
                    page_text,
                    document_name or path.name,
                    page_or_slide=f"{location_prefix} {page_index}",
                    image_path=str(image_path),
                )
            )
    finally:
        document.close()
    return chunks


def _convert_presentation(path: Path, artifact_dir: Path) -> Path | None:
    """Convert a presentation to PDF when LibreOffice is available.

    Direct PPTX parsing remains the fallback so the app still works without
    LibreOffice. Conversion is used only to preserve original slide images.
    """
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        return None
    output_dir = artifact_dir / "converted"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [converter, "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    converted = output_dir / f"{path.stem}.pdf"
    return converted if converted.is_file() else None


def _render_presentation_images(pdf_path: Path, output_dir: Path) -> list[Path]:
    try:
        import fitz  # type: ignore
    except ImportError:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(pdf_path)
    if document.page_count > _MAX_RENDERED_PAGES:
        document.close()
        return []
    images: list[Path] = []
    try:
        for index, page in enumerate(document, start=1):
            image_path = output_dir / f"slide-{index}.png"
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(image_path)
            images.append(image_path)
    finally:
        document.close()
    return images


def _ingest_presentation(path: Path, artifact_dir: Path) -> list[DocumentChunk]:
    if path.suffix.casefold() != ".pptx":
        converted = _convert_presentation(path, artifact_dir)
        if converted is None:
            raise RuntimeError(f"{path.name} requires LibreOffice for conversion to PDF")
        return _ingest_pdf(
            converted,
            artifact_dir,
            location_prefix="slide",
            document_name=path.name,
        )
    try:
        from pptx import Presentation  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PPTX support requires python-pptx; install the optional dependencies") from exc
    presentation = Presentation(path)
    converted = _convert_presentation(path, artifact_dir)
    rendered = _render_presentation_images(converted, artifact_dir / "slides") if converted else []
    chunks: list[DocumentChunk] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        text = " ".join(shape.text for shape in slide.shapes if hasattr(shape, "text")).strip()
        text = text or "[Visual slide with no extractable text]"
        image_path = str(rendered[slide_index - 1]) if slide_index <= len(rendered) else None
        chunks.extend(ingest_text(text, path.name, page_or_slide=f"slide {slide_index}", image_path=image_path))
    return chunks


def _ingest_docx(path: Path) -> list[DocumentChunk]:
    try:
        from docx import Document  # type: ignore
    except ImportError as exc:
        raise RuntimeError("DOCX support requires python-docx; install the optional dependencies") from exc
    document = Document(path)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    return ingest_text(text, path.name)
