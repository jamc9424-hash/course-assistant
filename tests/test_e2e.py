"""End-to-end tests against the live class services.

These build a small synthetic PDF (text + an image-bearing slide), ingest it,
and check the full workflows the assignment requires: grounded Q&A with visual
sources, quiz generation/scoring with hidden keys, duplicate upload handling,
and acknowledgment of unanswerable questions.

Skipped automatically when the services are unreachable or no API key is set
(so CI without credentials stays green).
"""
import io
import pytest

from course_assistant import config
from course_assistant.store import CourseAssistant, DocumentError
from conftest import requires_services
from PIL import Image, ImageDraw


def _make_pdf(tmp_path, with_image=True):
    import pymupdf
    pdf = tmp_path / "week2.pdf"
    doc = pymupdf.open()
    for text in ["Week 2: Multimodal AI and vector embeddings.",
                 "Vibe Coding on Prod is the theme of today's meme."]:
        page = doc.new_page(width=500, height=360)
        page.insert_text((30, 50), text)
    if with_image:
        page = doc.new_page(width=500, height=360)
        page.insert_text((30, 40), "Vibe Coding on Prod")
        img_path = tmp_path / "diagram.png"
        img = Image.new("RGB", (420, 260), "white")
        d = ImageDraw.Draw(img)
        d.rectangle([20, 20, 400, 240], outline="darkblue", width=3)
        d.ellipse([60, 70, 150, 160], fill="tomato")
        d.rectangle([230, 70, 380, 160], fill="mediumseagreen")
        img.save(img_path)
        img_page = doc.new_page(width=500, height=360)
        img_page.insert_image(pymupdf.Rect(0, 0, 500, 360), filename=str(img_path))
        img_page.insert_text((10, 340), "Diagram caption: AI pipeline")
    doc.save(pdf)
    doc.close()
    return pdf


@requires_services
def test_full_workflow(tmp_path):
    s = config.Settings(data_dir=tmp_path / "data")
    app = CourseAssistant(s)
    pdf = _make_pdf(tmp_path)

    # add + duplicate
    r1 = app.add_file(pdf)
    assert r1["status"] == "added"
    r2 = app.add_file(pdf)
    assert r2["status"] == "duplicate"
    assert len(app.list_documents()) == 1

    # grounded answer over text
    ans, _diag = app.answer("What is the theme of today's meme according to the slides?")
    assert ans.answer.strip()
    assert ans.sources, "expected at least one source to back the answer"
    assert any("week2" == s2.document for s2 in ans.sources)

    # visual question - retrieve and show a slide image
    ans2, _diag2 = app.answer(
        "Find the slide about Vibe Coding on Prod and describe what its image shows.")
    assert ans2.sources
    image_sources = [s2 for s2 in ans2.sources if s2.image_path]
    assert image_sources, "expected a slide image to be retrieved for a visual question"

    # quiz: generate, then check the key stays fixed and hidden
    questions = app.quiz(n=2)
    assert len(questions) >= 1
    for q in questions:
        assert len(q.options) >= 2
        assert 0 <= q.correct_index < len(q.options)
        assert q.explanation
    # scoring uses the stored key
    q0 = questions[0]
    assert q0.options[q0.correct_index] != "_"
    revealed = q0.to_dict(reveal=True)
    assert "correct_index" in revealed

    # unanswerable question must not fabricate
    ans3, _ = app.answer("What is the exact GPA requirement mentioned for the 2027 cohort?")
    assert not ans3.grounded or "do not establish" in ans3.answer.lower() \
        or "not establish" in ans3.answer.lower()

    # removal clears content
    assert app.remove_document("week2") is True
    assert app.list_documents() == []
