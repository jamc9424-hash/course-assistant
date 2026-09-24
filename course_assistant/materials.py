"""Generate synthetic sample course materials for demo / evaluation.

This creates a small PDF slide-deck plus a syllabus text file under
``materials/`` (this directory is gitignored — no course files are committed).
The deck intentionally mirrors the structure the real course materials use
(including a "Vibe Coding on Prod" style meme slide with an image and a couple
of diagram/chart slides) so that every evaluation path can be exercised without
depending on restricted Canvas downloads.

Run:  python -m course_assistant.materials
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

MATERIALS = Path(__file__).resolve().parent.parent / "materials"


def _font(size: int):
    from PIL import ImageFont
    for name in ("DejaVuSans.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "Arial.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _text(draw, cx, cy, s, fill="black", size=16):
    f = _font(size)
    bb = draw.textbbox((0, 0), s, font=f)
    draw.text((cx - (bb[2] - bb[0]) / 2, cy - (bb[3] - bb[1]) / 2), s,
              font=f, fill=fill)


def _meme(draw, w, h, _font):
    draw.rectangle([0, 0, w, 70], fill="black")
    draw.rectangle([0, h - 70, w, h], fill="black")
    _text(draw, w / 2, 35, "VIBE CODING on PROD", fill="white", size=20)
    _text(draw, w / 2, h - 35, "IT WORKS IN MY HEAD / OH NO", fill="white", size=14)
    draw.rectangle([60, 120, 260, 300], outline="white", width=3)
    draw.ellipse([90, 150, 230, 290], fill="tomato")
    draw.rectangle([300, 120, 500, 300], outline="white", width=3)
    _text(draw, 400, 210, "PROD", fill="white", size=18)


def _diagram(draw, w, h, _font):
    draw.rectangle([20, 20, w - 20, h - 20], outline="navy", width=3)
    boxes = [("PDFs", 40, 80), ("Slides", 150, 80), ("Text", 260, 80),
             ("Retrieve", 400, 160), ("Answer+Quiz", 400, 300)]
    for label, x, y in boxes:
        draw.rectangle([x - 40, y - 18, x + 60, y + 18], outline="black", width=2)
        _text(draw, x + 10, y, label, size=12)
    draw.line([(150, 120), (150, 160)], fill="gray", width=3)
    draw.line([(260, 120), (260, 160)], fill="gray", width=3)
    draw.line([(150, 160), (410, 178)], fill="gray", width=3)


def _chart(draw, w, h, _font):
    vals = [(40, 200), (140, 120), (240, 160), (340, 80), (440, 110)]
    for i in range(len(vals) - 1):
        x1, y1 = vals[i]
        x2, y2 = vals[i + 1]
        draw.line([(x1, y1), (x2, y2)], fill="mediumseagreen", width=4)
    for x, y in vals:
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill="darkgreen")
    _text(draw, w / 2, 20, "Accuracy over weeks", size=14)


def _slide(doc, title, body_lines, img=None):
    page = doc.new_page(width=560, height=320)
    page.insert_text((24, 40), title, fontsize=20, fontname="helv")
    y = 70
    for line in body_lines:
        page.insert_text((24, y), line, fontsize=12, fontname="helv")
        y += 22
    if img:
        rect = img[0]
        page.insert_image(rect, filename=img[1])
    return page


def _do_page_img(draw_fn, text_top=""):
    w, h = 500, 300
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    if text_top:
        _text(d, w / 2, 14, text_top, size=14)
    draw_fn(d, w, h, _font)
    path = MATERIALS / "out" / f"slide_img_{len(list((MATERIALS/'out').glob('*.png')))}.png"
    img.save(path)
    return path


def make_materials() -> list[Path]:
    import pymupdf
    MATERIALS.mkdir(parents=True, exist_ok=True)
    (MATERIALS / "out").mkdir(exist_ok=True)

    deck = MATERIALS / "week2_sample_slides.pdf"
    doc = pymupdf.open()
    _slide(doc, "Week 2: Multimodal AI builds smarter assistants", [
        "We architect assistants that ground answers in their own course materials.",
        "Key ideas: retrieval-augmented generation, vector embeddings, rerankers.",
    ])
    _slide(doc, "Agenda", [
        "Hybrid retrieval: keyword + text embeddings + visual embeddings",
        "Showing actual slide images as evidence",
        "Fixed-key practice quizzes with explanations",
    ])
    _slide(doc, "Vibe Coding on Prod (meme)", [
        "Retrieval should surface this slide and show the actual image.",
    ], img=(pymupdf.Rect(40, 120, 520, 300), str(_do_page_img(_meme, "Vibe Coding meme"))))
    _slide(doc, "Hybrid RAG architecture", [
        "Separate keyword, text-vector, and visual-vector indexes.",
        "Candidates are merged (RRF) and reranked by a multimodal reranker.",
        "Answers must carry real source excerpts and slide images.",
    ], img=(pymupdf.Rect(20, 200, 540, 300), str(_do_page_img(_diagram, "RAG pipeline diagram"))))
    _slide(doc, "Evidence policy", [
        "If the materials do not establish an answer, say so.",
        "Never invent facts or citations.",
    ])
    _slide(doc, "Practice quizzes", [
        "Fixed answer keys, hidden until you answer or request the key.",
        "Explanations point back to a specific slide or section.",
    ])
    _slide(doc, "Evaluation: accuracy over weeks", [
        "We track grounded answering and source support across the term.",
    ], img=(pymupdf.Rect(40, 200, 520, 300), str(_do_page_img(_chart, "Accuracy trend"))))
    doc.save(deck)
    doc.close()

    syl = MATERIALS / "syllabus_sample.txt"
    syl.write_text(
        "MBAX 6418 - Build a Course Assistant (sample syllabus)\n"
        "Grading: grounded answers 40%, visual evidence 25%, quizzes 20%, "
        "documentation 15%.\n"
        "No textbook is required; all materials are provided on Canvas.\n"
        "The course meets weekly and the final project is a working course "
        "assistant submitted to a shared team repository.\n",
        encoding="utf-8",
    )
    return [deck, syl]


if __name__ == "__main__":
    files = make_materials()
    print("Wrote sample materials:")
    for f in files:
        print("  ", f)
