from pathlib import Path

from course_assistant.assistant import CourseAssistant
from course_assistant.ingest import ingest_text
from course_assistant.models import SourceEvidence


def test_visual_retrieval_returns_slide_image_and_location():
    slide = ingest_text(
        "A meme contrasts batch and stream processing.",
        "lecture-slides.pdf",
        page_or_slide="slide 12",
        image_path="artifacts/lecture-slides/page-12.png",
    )[0]
    response = CourseAssistant.from_chunks([slide]).ask("What does the meme contrast?")

    assert response.sources[0].document == "lecture-slides.pdf"
    assert response.sources[0].page_or_slide == "slide 12"
    assert response.sources[0].image_path.endswith("page-12.png")


def test_visual_description_is_added_from_parser_service():
    class FakeVisualService:
        def embed_text(self, texts):
            return [[1.0, 0.0] for _ in texts]

        def embed_visual(self, inputs):
            return [[1.0, 0.0] for _ in inputs]

        def rerank(self, query, documents):
            return [1.0 for _ in documents]

        def parse_image(self, image_data_url, instruction):
            assert image_data_url.startswith("data:image/")
            assert "chart" in instruction.casefold() or "diagram" in instruction.casefold()
            return {"choices": [{"message": {"content": "The visual compares batch processing with stream processing."}}]}

    image = Path("C:/Users/mcken/AppData/Local/Temp/course-assistant-visual.png")
    image.write_bytes(b"not really an image, but enough for the request adapter")
    try:
        chunk = ingest_text(
            "Slide 12 contains a meme.",
            "lecture-slides.pdf",
            page_or_slide="slide 12",
            image_path=str(image),
        )[0]
        response = CourseAssistant.from_chunks([chunk], service_client=FakeVisualService()).ask("Explain the meme and diagram.")
    finally:
        image.unlink(missing_ok=True)

    assert "visual compares" in response.answer.casefold()
    assert response.sources[0].page_or_slide == "slide 12"
