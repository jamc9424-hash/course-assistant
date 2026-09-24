"""Document parsing and page/slide rendering.

Turns an uploaded course file into:
  - ordered *pages*: ``Page(text, image_path|None, section|None)``
  - a page image (.png) for every page/slide the format can render

Supported file formats and how each is handled:
  PDF   -> native text + native per-page rendering (PyMuPDF). Pages whose text
           layer is empty are OCR'd via the class document parser (9005).
  PPTX  -> text extracted per slide (python-pptx). Slide *images* require a
           manual "Save as PDF" export or LibreOffice (see ``soffice`` flag);
           both are optional, documented limitations.
  DOCX  -> text extracted (python-docx). No per-page rendering without
           LibreOffice/manual export.
  TXT/MD-> read as plain text, treated as one page.
  PNG/JPG -> treated as a single image page (for direct image uploads).

Everything here is deterministic / offline except OCR (which calls the class
parser and degrades to the extracted text if OCR fails).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .service import DocumentParserClient, ServiceError
from .types import VisualRecord

try:
    import pymupdf  # modern API; `fitz` is the legacy alias
except Exception:  # pragma: no cover
    import fitz as pymupdf


SUPPORTED_TEXT = {".pdf", ".pptx", ".docx", ".txt", ".md"}
SUPPORTED_IMAGE = {".png", ".jpg", ".jpeg"}


class UnsupportedFormatError(ValueError):
    pass


@dataclass
class Page:
    text: str
    index: int
    image_path: Optional[str] = None
    section: Optional[str] = None


@dataclass
class ParsedDocument:
    title: str
    source_path: Path
    pages: list[Page] = field(default_factory=list)

    @property
    def image_pages(self) -> list[VisualRecord]:
        records = []
        for p in self.pages:
            if p.image_path:
                records.append(
                    VisualRecord(
                        document=self.title,
                        page=p.index + 1,
                        section=p.section,
                        image_path=p.image_path,
                        caption=(p.section or "") + " " + p.text[:400].strip(),
                    )
                )
        return records


def _find_soffice() -> Optional[str]:
    candidates = [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


def _convert_to_pdf(path: Path, workdir: Path, soffice: str) -> Optional[Path]:
    """Convert a docx/pptx to PDF via LibreOffice into workdir. Returns PDF path."""
    out_pdf = workdir / (path.stem + ".pdf")
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", str(workdir), str(path.resolve())],
            check=True, capture_output=True, timeout=180,
        )
    except Exception:
        return None
    return out_pdf if out_pdf.exists() else None


def _pdf_pages(pdf_path: Path, workdir: Path,
               parser: Optional[DocumentParserClient]) -> list[Page]:
    doc = pymupdf.open(pdf_path)
    pages: list[Page] = []
    for i, page in enumerate(doc):
        text = page.get_text("text", sort=True).strip()
        img = workdir / f"page_{i + 1}.png"
        pix = page.get_pixmap(dpi=110)
        pix.save(img)
        section = _first_heading(text) or None
        if not text and parser is not None:
            try:
                text = parser.parse_image(str(img))
            except ServiceError:
                pass
        pages.append(Page(text=text, index=i, image_path=str(img), section=section))
    doc.close()
    return pages


def _first_heading(text: str) -> Optional[str]:
    # Heuristic first non-empty, short line as the section heading.
    for line in text.splitlines():
        line = line.strip()
        if line and len(line) <= 80:
            candidate = re.sub(r"\s+", " ", line)
            if candidate:
                return candidate
    return None


def _pptx_pages(path: Path) -> list[Page]:
    from pptx import Presentation
    prs = Presentation(str(path))
    pages: list[Page] = []
    for i, slide in enumerate(prs.slides):
        parts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = "".join(run.text for run in para.runs).strip()
                    if t:
                        parts.append(t)
            if shape.has_table:
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    parts.append(" | ".join(cells))
        text = "\n".join(parts).strip()
        pages.append(Page(text=text, index=i, section=_first_heading(text)))
    return pages


def _docx_pages(path: Path) -> list[Page]:
    from docx import Document
    doc = Document(str(path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                paragraphs.append(" ".join(cells))
    text = "\n".join(paragraphs).strip()
    return [Page(text=text, index=0, section=_first_heading(text))]


def _text_pages(path: Path) -> list[Page]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return [Page(text=text, index=0, section=_first_heading(text))]


def _image_pages(path: Path, workdir: Path) -> list[Page]:
    # Copy/convert the uploaded image to a PNG page for uniform indexing.
    target = workdir / "page_1.png"
    import shutil as _sh
    _sh.copyfile(path, target)
    return [Page(text="", index=0, image_path=str(target), section=None)]


def parse_document(
    path: Path,
    out_dir: Path,
    parser: Optional[DocumentParserClient] = None,
    allow_libreoffice: bool = True,
) -> ParsedDocument:
    """Parse one file into a :class:`ParsedDocument`.

    ``out_dir`` is where rendered page images are written (gitignored data dir).
    """
    path = Path(path)
    suffix = path.suffix.lower()
    out_dir.mkdir(parents=True, exist_ok=True)

    if suffix in SUPPORTED_IMAGE:
        pages = _image_pages(path, out_dir)
    elif suffix == ".pdf":
        pages = _pdf_pages(path, out_dir, parser)
    elif suffix == ".pptx":
        pages = _pptx_pages(path)
        _attach_converted_images(path, out_dir, pages, allow_libreoffice)
    elif suffix == ".docx":
        pages = _docx_pages(path)
        _attach_converted_images(path, out_dir, pages, allow_libreoffice)
    elif suffix in (".txt", ".md"):
        pages = _text_pages(path)
    else:
        raise UnsupportedFormatError(
            f"Unsupported file type {suffix}. Supported: "
            + ", ".join(sorted(SUPPORTED_TEXT | SUPPORTED_IMAGE))
        )

    return ParsedDocument(title=path.stem, source_path=path.resolve(), pages=pages)


def _attach_converted_images(
    path: Path, out_dir: Path, pages: list[Page], allow_libreoffice: bool
) -> None:
    """If LibreOffice is present, convert pptx/docx -> pdf and attach renderings."""
    recent = Path(__file__).resolve().parent
    workdir = out_dir / "conv"
    workdir.mkdir(parents=True, exist_ok=True)
    soffice = _find_soffice() if allow_libreoffice else None
    if soffice is None:
        return
    pdf = _convert_to_pdf(path, workdir, soffice)
    if pdf is None or not pdf.exists():
        return
    try:
        rendered = _pdf_pages(pdf, out_dir, None)
    except Exception:
        return
    for page in pages:
        if page.index < len(rendered):
            page.image_path = rendered[page.index].image_path
