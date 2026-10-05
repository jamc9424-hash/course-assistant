from __future__ import annotations

import json
import os
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


def _refresh_session():
    """Reset materials, filters, answers, quiz state, and visible outputs."""
    return (
        MaterialStore(),
        None,
        [],
        "Study session refreshed. Add materials to begin again.",
        "",
        "",
        "",
        {"answer": "", "sources": []},
        [],
        "",
        None,
        "{}",
        "",
        "",
    )


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


def _quiz_markdown(quiz: Quiz) -> str:
    lines = [
        "## Practice test",
        "Work through each question before checking your answers. Solutions remain hidden until you submit or reveal one.",
        "",
    ]
    for index, question in enumerate(quiz.questions, start=1):
        lines.append(f"### {index}. {question.prompt}")
        for choice_index, choice in enumerate(question.choices):
            letter = chr(65 + choice_index)
            lines.append(f"- **{letter}.** {choice}")
        lines.append("")
    return "\n".join(lines).strip()


def _feedback_markdown(feedback: dict[str, object]) -> str:
    score = int(feedback.get("score", 0))
    total = int(feedback.get("total", 0))
    answered = int(feedback.get("answered", 0))
    lines = [
        "## Practice test results",
        f"### Score: **{score} / {total}**",
        f"Answered: **{answered} of {total}**",
        "",
    ]
    items = feedback.get("feedback", [])
    if not items:
        lines.append("Answer at least one question or enter a question ID to reveal its solution.")
        return "\n".join(lines)
    lines.append("### Review your responses")
    for item in items:
        if not isinstance(item, dict):
            continue
        question_id = item.get("question_id", "question")
        icon = "✅ Correct" if item.get("correct") else "❌ Review"
        lines.append(f"#### {icon} · {question_id}")
        if item.get("answered"):
            selected = item.get("selected_choice")
            lines.append(f"Your choice: **Option {int(selected) + 1}**")
        lines.append(f"Correct choice: **Option {int(item.get('correct_choice', 0)) + 1}**")
        explanation = str(item.get("explanation", "")).strip()
        if explanation:
            lines.append(f"\n> {explanation}")
        source = item.get("source", {})
        if isinstance(source, dict):
            location = source.get("page_or_slide") or source.get("section") or "selected material"
            document = source.get("document", "course material")
            excerpt = str(source.get("excerpt", "")).strip()
            lines.append(f"\n**Source:** `{document}` · {location}")
            if excerpt:
                lines.append(f"> {excerpt}")
        lines.append("")
    return "\n".join(lines).strip()


def _quiz(store: MaterialStore | None, material: str, topic: str, count: int) -> tuple[str, Quiz | None]:
    try:
        quiz = _assistant_from_store(store or MaterialStore()).quiz(material or None, topic or None, int(count))
    except (ValueError, OSError) as exc:
        return json.dumps({"error": str(exc)}), None
    return _quiz_markdown(quiz), quiz


def _score(quiz: Quiz | None, answers_json: str, reveal_question_id: str) -> str:
    if quiz is None:
        return json.dumps({"error": "generate a quiz first"})
    try:
        answers = json.loads(answers_json or "{}")
        if not isinstance(answers, dict):
            raise ValueError("answers must be a JSON object of question_id to choice index")
        from .quiz import feedback_quiz
        return _feedback_markdown(
            feedback_quiz(
                quiz,
                {str(k): int(v) for k, v in answers.items()},
                reveal_question_id=reveal_question_id.strip() or None,
            )
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return json.dumps({"error": f"answers must be a JSON object of question_id to choice index: {exc}"})


QUIZLET_CSS = """
:root {
  --study-blue: #4255ff;
  --study-blue-dark: #2938c7;
  --study-ink: #17213a;
  --study-muted: #64708b;
  --study-line: #e5e9f2;
  --study-bg: #f6f7fb;
  --study-card: #ffffff;
  --study-green: #17834b;
}
body, .gradio-container { background: var(--study-bg) !important; color: var(--study-ink) !important; }
.gradio-container { max-width: 1240px !important; margin: 0 auto !important; }
#study-header { margin: -16px -16px 0; padding: 18px 34px; background: #fff; border-bottom: 1px solid var(--study-line); }
.study-nav { display: flex; align-items: center; justify-content: space-between; gap: 18px; max-width: 1170px; margin: auto; }
.study-brand { display: flex; align-items: center; gap: 11px; font-weight: 800; letter-spacing: -.03em; font-size: 21px; }
.study-logo { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: var(--study-blue); color: white; font-size: 18px; box-shadow: 0 5px 14px #4255ff35; }
.study-nav-note { color: var(--study-muted); font-size: 13px; font-weight: 600; }
#study-shell { max-width: 1170px; margin: auto; }
.study-hero { padding: 42px 4px 28px; }
.study-kicker { color: var(--study-blue); font-size: 12px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; margin-bottom: 10px; }
.study-hero h1 { color: var(--study-ink); font-size: 38px; line-height: 1.05; letter-spacing: -.045em; margin: 0 0 12px; }
.study-hero p { color: var(--study-muted); max-width: 720px; font-size: 16px; line-height: 1.55; margin: 0; }
.study-card { background: var(--study-card); border: 1px solid var(--study-line); border-radius: 18px; padding: 22px; box-shadow: 0 8px 24px #17213a0b; margin-bottom: 18px; }
.study-card h2 { color: var(--study-ink); font-size: 19px; margin: 0 0 5px; letter-spacing: -.02em; }
.study-card .study-help { color: var(--study-muted); font-size: 13px; margin-bottom: 15px; }
.study-section-label { color: var(--study-muted); font-size: 11px; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; margin: 2px 0 9px; }
.study-upload { border: 1.5px dashed #b9c2ff !important; background: #f8f9ff !important; border-radius: 14px !important; }
.study-upload:hover { border-color: var(--study-blue) !important; background: #f2f4ff !important; }
button.primary { background: var(--study-blue) !important; border-color: var(--study-blue) !important; color: white !important; font-weight: 750 !important; border-radius: 10px !important; }
button.primary:hover { background: var(--study-blue-dark) !important; border-color: var(--study-blue-dark) !important; }
button.secondary { border-radius: 10px !important; font-weight: 700 !important; }
textarea, input, .input-container, .gr-box { border-radius: 10px !important; }
.tab-nav { border-bottom: 1px solid var(--study-line) !important; gap: 22px; }
.tab-nav button { color: var(--study-muted) !important; font-weight: 750 !important; border: 0 !important; }
.tab-nav button.selected { color: var(--study-blue) !important; border-bottom: 3px solid var(--study-blue) !important; }
.study-output { border-radius: 14px !important; border: 1px solid var(--study-line) !important; }
.study-tip { color: var(--study-muted); font-size: 12px; line-height: 1.45; padding-top: 8px; }
@media (max-width: 700px) { .study-hero h1 { font-size: 30px; } #study-header { padding: 16px 20px; } .study-nav-note { display: none; } .study-card { padding: 16px; } }
"""


def build_app():
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError("Install the optional UI dependencies before launching the Gradio app") from exc

    with gr.Blocks(title="Course Assistant | Study smarter") as demo:
        gr.HTML(
            """<div id="study-header"><div class="study-nav">
            <div class="study-brand"><span class="study-logo">✦</span><span>Course Assistant</span></div>
            <div class="study-nav-note">Your focused study workspace</div>
            </div></div>"""
        )
        with gr.Column(elem_id="study-shell"):
            gr.HTML(
                """<div class="study-hero"><div class="study-kicker">Learn with your course materials</div>
                <h1>Turn your notes into momentum.</h1>
                <p>Upload your course content, ask grounded questions, and build practice quizzes with evidence you can trust.</p></div>"""
            )
            store_state = gr.State(MaterialStore())
            with gr.Group(elem_classes="study-card"):
                gr.Markdown("## 1. Build your study set", elem_classes="study-heading")
                gr.Markdown("Add slides, readings, and notes. Duplicate files are skipped automatically.", elem_classes="study-help")
                gr.Markdown("COURSE MATERIALS", elem_classes="study-section-label")
                files = gr.File(file_count="multiple", type="filepath", label="Drop files here or browse", elem_classes="study-upload")
                materials_view = gr.JSON(label="Your study set", elem_classes="study-output")
                upload_status = gr.Markdown()
                refresh_button = gr.Button("↻ Refresh study session", variant="secondary")
                files.upload(_add_files, [files, store_state], [store_state, materials_view, upload_status])
                with gr.Row():
                    remove_id = gr.Textbox(label="Document ID to remove", scale=3)
                    remove_button = gr.Button("Remove from set", variant="secondary", scale=1)
                remove_button.click(_remove_file, [remove_id, store_state], [store_state, materials_view, upload_status])
            with gr.Group(elem_classes="study-card"):
                gr.Markdown("## 2. Study your way", elem_classes="study-heading")
                gr.Markdown("Choose a material or topic filter, then ask a question or practice what you know.", elem_classes="study-help")
                with gr.Row():
                    material = gr.Textbox(label="Material filename (optional)", placeholder="e.g. Week 2 slides")
                    topic = gr.Textbox(label="Topic filter (optional)", placeholder="e.g. prompt engineering")
                with gr.Tabs():
                    with gr.Tab("Ask a question"):
                        question = gr.Textbox(label="What do you want to understand?", placeholder="Ask about a concept, diagram, chart, or slide…", lines=3)
                        ask_button = gr.Button("Ask Course Assistant", variant="primary")
                        answer = gr.JSON(label="Answer and sources", elem_classes="study-output")
                        evidence_image = gr.Gallery(label="Retrieved visual evidence", columns=2, height="auto", elem_classes="study-output")
                        ask_button.click(_answer, [store_state, material, topic, question], [answer, evidence_image])
                    with gr.Tab("Practice quiz"):
                        with gr.Row():
                            count = gr.Number(value=5, minimum=1, maximum=20, precision=0, label="Number of questions")
                            quiz_button = gr.Button("Create practice quiz", variant="primary")
                        quiz_output = gr.Markdown("Your practice questions will appear here.", elem_classes="study-output")
                        quiz_state = gr.State(None)
                        quiz_button.click(_quiz, [store_state, material, topic, count], [quiz_output, quiz_state])
                        answers = gr.Code(value="{}", label="Submit answers · use question IDs and choice numbers, e.g. {\"q1\": 0}", language="json")
                        reveal_id = gr.Textbox(label="Reveal one solution (optional question ID)", placeholder="e.g. q1")
                        score_button = gr.Button("Check answers", variant="primary")
                        score = gr.Markdown("Your score and feedback will appear here.", elem_classes="study-output")
                        score_button.click(_score, [quiz_state, answers, reveal_id], score)
                gr.Markdown("Sources stay attached to answers and feedback so you can review the original material.", elem_classes="study-tip")
            refresh_button.click(
                _refresh_session,
                inputs=[],
                outputs=[store_state, files, materials_view, upload_status, material, topic, question, answer, evidence_image, quiz_output, quiz_state, answers, reveal_id, score],
            )
    return demo


def main() -> None:
    launch_kwargs = {"server_name": os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"), "css": QUIZLET_CSS}
    port = os.getenv("PORT") or os.getenv("GRADIO_SERVER_PORT")
    if port:
        try:
            server_port = int(port)
        except ValueError as exc:
            raise RuntimeError("PORT/GRADIO_SERVER_PORT must be an integer") from exc
        if not 1 <= server_port <= 65535:
            raise RuntimeError("PORT/GRADIO_SERVER_PORT must be between 1 and 65535")
        launch_kwargs["server_port"] = server_port
    build_app().launch(**launch_kwargs)


if __name__ == "__main__":
    main()
