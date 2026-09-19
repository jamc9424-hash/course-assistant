from __future__ import annotations

import json
from typing import Any

from .assistant import CourseAssistant
from .materials import MaterialStore
from .models import Quiz
from .services import ClassServiceClient, ServiceSettings


def _service_client() -> ClassServiceClient | None:
    settings = ServiceSettings.from_env()
    if not settings.api_key or settings.api_key == "replace-with-local-dummy-value":
        return None
    return ClassServiceClient(settings)


def _assistant_from_store(store: MaterialStore) -> CourseAssistant:
    client = _service_client()
    if client:
        try:
            return CourseAssistant.from_chunks(store.chunks(), service_client=client)
        except RuntimeError:
            pass
    return CourseAssistant.from_chunks(store.chunks())


def _material_view(store: MaterialStore) -> list[dict[str, str]]:
    return [{"document_id": record.document_id, "filename": record.filename} for record in store.records()]


def _add_files(paths: list[str] | str | None, store: MaterialStore | None):
    store = store or MaterialStore()
    normalized = [paths] if isinstance(paths, str) else (paths or [])
    added = []
    duplicates = []
    errors = []
    for path in normalized:
        try:
            before = set(store.document_ids())
            record = store.add_file(path)
            (duplicates if record.document_id in before else added).append(record.filename)
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    messages = []
    if added:
        messages.append(f"Added {len(added)} document(s): {', '.join(added)}")
    if duplicates:
        messages.append(f"Skipped {len(duplicates)} duplicate upload(s)")
    if errors:
        messages.append("Upload errors: " + " | ".join(errors))
    return store, _material_view(store), "; ".join(messages) or "No files selected."


def _remove_file(document_id: str | None, store: MaterialStore | None):
    store = store or MaterialStore()
    if not document_id:
        return store, _material_view(store), "Enter a document ID to remove."
    removed = store.remove(document_id.strip())
    status = "Document removed from searchable materials." if removed else "Document ID was not found."
    return store, _material_view(store), status


def _answer(store: MaterialStore | None, material: str, topic: str, question: str) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    if not question.strip():
        return {"answer": "Enter a question.", "sources": []}, []
    response = _assistant_from_store(store or MaterialStore()).ask(question, material or None, topic or None)
    image_paths = []
    for source in response.sources:
        if source.image_path:
            location = source.page_or_slide or source.section or "source visual"
            image_paths.append((source.image_path, f"{source.document} — {location}"))
    return response.as_dict(), list(dict.fromkeys(image_paths))


def _quiz(store: MaterialStore | None, material: str, topic: str, count: int) -> tuple[str, Quiz | None]:
    try:
        quiz = _assistant_from_store(store or MaterialStore()).quiz(material or None, topic or None, int(count))
    except (ValueError, OSError) as exc:
        return json.dumps({"error": str(exc)}), None
    return json.dumps({"questions": [question.public_dict() for question in quiz.questions]}, indent=2), quiz


def _score(quiz: Quiz | None, answers_json: str, reveal_question_id: str) -> str:
    if quiz is None:
        return json.dumps({"error": "generate a quiz first"})
    try:
        answers = json.loads(answers_json or "{}")
        from .quiz import feedback_quiz
        return json.dumps(
            feedback_quiz(
                quiz,
                {str(k): int(v) for k, v in answers.items()},
                reveal_question_id=reveal_question_id.strip() or None,
            ),
            indent=2,
        )
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
            "Upload PDF, PPTX, DOCX, TXT, or Markdown course files. Uploading the same content twice is skipped. "
            "Remove a document at any time; its searchable text and generated page images are removed from this session."
        )
        store_state = gr.State(MaterialStore())
        files = gr.File(file_count="multiple", type="filepath", label="Add course materials")
        materials_view = gr.JSON(label="Uploaded materials")
        upload_status = gr.Markdown()
        files.upload(_add_files, [files, store_state], [store_state, materials_view, upload_status])
        with gr.Row():
            remove_id = gr.Textbox(label="Document ID to remove")
            remove_button = gr.Button("Remove document")
        remove_button.click(_remove_file, [remove_id, store_state], [store_state, materials_view, upload_status])

        material = gr.Textbox(label="Material filename filter (optional)")
        topic = gr.Textbox(label="Topic filter (optional)")
        with gr.Tab("Ask"):
            question = gr.Textbox(label="Question")
            answer = gr.JSON(label="Answer and sources")
            evidence_image = gr.Gallery(label="Retrieved slide images", columns=2, height="auto")
            gr.Button("Answer").click(_answer, [store_state, material, topic, question], [answer, evidence_image])
        with gr.Tab("Practice quiz"):
            count = gr.Number(value=5, minimum=1, maximum=20, precision=0, label="Question count")
            quiz_output = gr.Code(label="Quiz JSON (solutions hidden)", language="json")
            quiz_state = gr.State(None)
            gr.Button("Generate quiz").click(_quiz, [store_state, material, topic, count], [quiz_output, quiz_state])
            answers = gr.Code(value="{}", label="Answers JSON, e.g. {\"q1\": 0}", language="json")
            reveal_id = gr.Textbox(label="Request solution for question ID (optional)")
            score = gr.Code(label="Score and feedback", language="json")
            gr.Button("Score quiz / show answered feedback").click(_score, [quiz_state, answers, reveal_id], score)
    return demo


def main() -> None:
    build_app().launch()


if __name__ == "__main__":
    main()
