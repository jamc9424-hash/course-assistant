from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .assistant import CourseAssistant
from .ingest import ingest_file
from .models import Quiz
from .services import ClassServiceClient, ServiceSettings


def _assistant_from_paths(paths: list[str]) -> CourseAssistant:
    chunks = []
    for path in paths or []:
        chunks.extend(ingest_file(path))
    settings = ServiceSettings.from_env()
    client = ClassServiceClient(settings) if settings.api_key and settings.api_key != "replace-with-local-dummy-value" else None
    return CourseAssistant.from_chunks(chunks, service_client=client)


def _answer(paths: list[str], material: str, topic: str, question: str) -> tuple[dict[str, Any], str | None]:
    if not question.strip():
        return {"answer": "Enter a question.", "sources": []}, None
    response = _assistant_from_paths(paths).ask(question, material or None, topic or None)
    image_path = next((source.image_path for source in response.sources if source.image_path), None)
    return response.as_dict(), image_path


def _quiz(paths: list[str], material: str, topic: str, count: int) -> tuple[str, Quiz | None]:
    try:
        quiz = _assistant_from_paths(paths).quiz(material or None, topic or None, int(count))
    except (ValueError, OSError) as exc:
        return json.dumps({"error": str(exc)}), None
    return json.dumps({"questions": [question.public_dict() for question in quiz.questions]}, indent=2), quiz


def _score(quiz: Quiz | None, answers_json: str) -> str:
    if quiz is None:
        return json.dumps({"error": "generate a quiz first"})
    try:
        answers = json.loads(answers_json or "{}")
        from .quiz import score_quiz
        return json.dumps(score_quiz(quiz, {str(k): int(v) for k, v in answers.items()}), indent=2)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return json.dumps({"error": f"answers must be a JSON object of question_id to choice index: {exc}"})


def build_app():
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError("Install the optional UI dependencies before launching the Gradio app") from exc

    with gr.Blocks(title="Course Assistant") as demo:
        gr.Markdown(
            "# Course Assistant\n"
            "Upload PDF, PPTX, DOCX, TXT, or Markdown course files. The app preserves source locations "
            "and PDF page images, answers only from retrieved material, and reports when evidence is missing."
        )
        files = gr.File(file_count="multiple", type="filepath", label="Course materials")
        material = gr.Textbox(label="Material filter (optional)")
        topic = gr.Textbox(label="Topic filter (optional)")
        with gr.Tab("Ask"):
            question = gr.Textbox(label="Question")
            answer = gr.JSON(label="Answer and sources")
            evidence_image = gr.Image(label="Visual evidence", type="filepath")
            gr.Button("Answer").click(_answer, [files, material, topic, question], [answer, evidence_image])
        with gr.Tab("Practice quiz"):
            count = gr.Number(value=5, minimum=1, maximum=20, precision=0, label="Question count")
            quiz_output = gr.Code(label="Quiz JSON (solutions hidden)", language="json")
            quiz_state = gr.State(None)
            gr.Button("Generate quiz").click(_quiz, [files, material, topic, count], [quiz_output, quiz_state])
            answers = gr.Code(value="{}", label="Answers JSON, e.g. {\"q1\": 0}", language="json")
            score = gr.Code(label="Score", language="json")
            gr.Button("Score quiz").click(_score, [quiz_state, answers], score)
    return demo


def main() -> None:
    build_app().launch()


if __name__ == "__main__":
    main()
