"""Gradio interface for the Course Assistant.

Tabs:
  Manage materials  -> add / list / remove course documents.
  Ask a question    -> grounded Q&A with document/slide sources + slide images.
  Practice quiz     -> generate fixed-answer MCQs; scores/keys hidden until
                       the student answers or requests them.

Run locally with:  python -m course_assistant.app
"""
from __future__ import annotations

import gradio as gr

from .store import CourseAssistant, DocumentError

QMAX = 6

HEADER = """
<div style="font-family:-apple-system,'Segoe UI',system-ui,sans-serif;max-width:980px;margin:0 auto;padding:18px 6px">
  <div style="font-size:26px;font-weight:700;letter-spacing:-0.5px">📚 Course Assistant</div>
  <div style="color:var(--body-text-color-subdued);margin-top:4px;line-height:1.55">
    Grounded, multimodal course assistant. Answers are built only from your uploaded
    materials and carry document/page/slide sources with real excerpts and screenshots.
  </div>
</div>
"""
PRIVACY = (
    "_Endpoint URLs and API keys are read from your local `.env` (gitignored) "
    "and are never shown in this interface._"
)


def _fmt_sources(sources) -> str:
    if not sources:
        return "_No sources cited._"
    lines, seen = [], set()
    for s in sources:
        key = (s.document, s.page, s.section)
        if key in seen:
            continue
        seen.add(key)
        loc = f"**{s.document}**"
        if s.page:
            loc += f" · page {s.page}"
        if s.section:
            loc += f" · _{s.section}_"
        lines.append(f"- {loc}")
        if s.excerpt:
            lines.append(f"  > {s.excerpt.strip()[:220]}")
    return "\n".join(lines) if lines else "_No sources cited._"


def _fmt_answer(a) -> str:
    badge = "✅ grounded in materials" if a.grounded else "⚠️ not established by materials"
    note = f"\n\n_{a.note}_" if a.note else ""
    conf = f"{a.confidence:.2f}" if a.confidence else "n/a"
    return (
        f"### Answer\n{a.answer}{note}\n\n"
        f"**{badge}** · confidence {conf} · {a.latency_ms:.0f} ms\n\n"
        f"### Sources\n{_fmt_sources(a.sources)}"
    )


def _doc_titles(assistant) -> list[str]:
    return [d["title"] for d in assistant.list_documents()]


def _choices(assistant) -> dict:
    return gr.update(choices=_doc_titles(assistant), value=None)


def _to_rows(docs) -> list[list]:
    return [[d["title"], d["source_name"], d["added"], d["chunks"],
             d["pages"], d["images"]] for d in docs]


def build(assistant: CourseAssistant) -> gr.Blocks:
    with gr.Blocks(title="Course Assistant") as demo:
        gr.HTML(HEADER)

        # ---------------- Tab 1: manage materials ----------------
        with gr.Tab("Manage materials"):
            upload = gr.File(label="Upload a course file (PDF, PPTX, DOCX, TXT, MD, PNG/JPG)",
                             file_count="multiple",
                             file_types=[".pdf", ".pptx", ".docx", ".txt", ".md",
                                         ".png", ".jpg", ".jpeg"])
            add_status = gr.Markdown("")
            doc_table = gr.Dataframe(headers=["title", "source", "added",
                                              "chunks", "pages", "images"],
                                     label="Loaded materials", interactive=False)
            with gr.Row():
                remove_dd = gr.Dropdown(label="Remove a document",
                                        choices=[], interactive=True)
                remove_btn = gr.Button("Remove", variant="stop")

            def _on_upload(files):
                msgs = []
                for f in files or []:
                    try:
                        r = assistant.add_file(f)
                        if r["status"] == "duplicate":
                            msgs.append(f"⏭️ **{r['title']}**: duplicate content — skipped.")
                        else:
                            msgs.append(f"✅ **{r['title']}**: {r['chunks']} chunks, "
                                        f"{r['images']} slide image(s) indexed.")
                    except DocumentError as e:
                        msgs.append(f"❌ **{e}**")
                titles = _doc_titles(assistant)
                return "\n".join(msgs) or "_(choose a file above)_", \
                    _to_rows(assistant.list_documents()), \
                    gr.update(choices=titles, value=None)

            def _on_remove(title):
                titles = _doc_titles(assistant)
                if not title:
                    return "_Select a document first._", \
                        _to_rows(assistant.list_documents()), \
                        gr.update(choices=titles, value=None)
                removed = assistant.remove_document(title)
                docs = assistant.list_documents()
                msg = f"🗑️ Removed **{title}**." if removed else f"⚠️ Not found: {title}"
                return msg, _to_rows(docs), gr.update(choices=_doc_titles(assistant), value=None)

            upload.upload(_on_upload, upload, [add_status, doc_table, remove_dd])
            remove_btn.click(_on_remove, remove_dd, [add_status, doc_table, remove_dd])

        # ---------------- Tab 2: ask a question ----------------
        with gr.Tab("Ask a question"):
            with gr.Row():
                q_text = gr.Textbox(label="Your question", lines=2,
                                    placeholder="e.g. What is the week 2 topic card? "
                                                "Find and describe the Vibe Coding on Prod memo.")
                topic_dd = gr.Dropdown(label="Material filter (optional)", choices=[],
                                       interactive=True)
            ask_btn = gr.Button("Ask", variant="primary")
            answer_md = gr.Markdown("")
            slide_gallery = gr.Gallery(label="Supporting slide image(s)", columns=2, height=320)

            def _on_ask(text, topic):
                topic = None if not topic else topic
                answer, _diag = assistant.answer(text, topic)
                images = [
                    (s.image_path, f"{s.document} — page {s.page}")
                    for s in answer.sources if s.image_path
                ]
                return _fmt_answer(answer), images

            ask_btn.click(_on_ask, [q_text, topic_dd], [answer_md, slide_gallery])

        # ---------------- Tab 3: practice quiz ----------------
        with gr.Tab("Practice quiz"):
            with gr.Row():
                n_slider = gr.Slider(1, QMAX, value=3, step=1, label="Number of questions")
                quiz_topic = gr.Dropdown(label="Topic filter (optional)", choices=[],
                                         interactive=True)
            gen_btn = gr.Button("Generate quiz", variant="primary")
            quiz_title = gr.Markdown("")
            quiz_state = gr.State([])

            q_md = []
            q_radio = []
            q_fb = []
            for i in range(QMAX):
                with gr.Column(visible=False) as panel:
                    q_md.append(gr.Markdown(f"### Q{i + 1}"))
                    q_radio.append(gr.Radio(choices=[], label="Options"))
                    q_fb.append(gr.Markdown(""))

            with gr.Row():
                check_btn = gr.Button("Check my answers", variant="secondary")
                reveal_btn = gr.Button("Reveal answer key")
            score_md = gr.Markdown("")

            def _retract_all(prefix):
                return (prefix, [],
                        *[gr.update() for _ in range(QMAX * 3)])

            def _on_generate(n, topic):
                topic = None if not topic else topic
                if not assistant.list_documents():
                    return _retract_all("❌ **No materials loaded.** Add a document first.")
                try:
                    qs = assistant.quiz(n=int(n), topic=topic)
                except DocumentError as e:
                    return _retract_all(f"❌ {e}")
                state_qs = [{
                    "question": q.question, "options": q.options,
                    "correct_index": q.correct_index, "explanation": q.explanation,
                    "sources": [s.to_dict() for s in q.sources],
                } for q in qs]
                updates = []
                for i in range(QMAX):
                    if i < len(qs):
                        q = qs[i]
                        updates += [gr.update(visible=True, value=f"### Q{i + 1}: {q.question}"),
                                    gr.update(choices=q.options, value=None, label="Options"),
                                    gr.update(value="")]
                    else:
                        updates += [gr.update(visible=False),
                                    gr.update(choices=[], value=None),
                                    gr.update(value="")]
                return (f"Quiz ready — **{len(qs)} question(s)** from the loaded materials.\n"
                        f"Select an option for each, then *Check my answers*.", state_qs, *updates)

            def _on_check(state, *radios):
                qs = state
                if not qs:
                    return ("_Generate a quiz first._",
                            *(["_Generate a quiz first._"] * QMAX))
                correct = 0
                fbs = []
                for i in range(QMAX):
                    if i < len(qs):
                        q = qs[i]
                        chosen = radios[i]
                        exp = q["explanation"] or "_no explanation_"
                        if chosen is not None and chosen == q["options"][q["correct_index"]]:
                            correct += 1
                            fbs.append(f"✅ **Correct.** — {exp}")
                        elif chosen is None:
                            fbs.append(f"⬜ *Not answered.* — _{exp}_")
                        else:
                            fbs.append(f"❌ **Incorrect.** Correct: **{q['options'][q['correct_index']]}** — {exp}")
                    else:
                        fbs.append("")
                return (f"### Score: **{correct}/{len(qs)}**", *fbs)

            def _on_reveal(state):
                qs = state
                if not qs:
                    return ("_Generate a quiz first._",
                            *(["_Generate a quiz first._"] * QMAX))
                fbs = [f"🔑 Correct: **{q['options'][q['correct_index']]}** — {q['explanation']}"
                       for q in qs] + [""] * (QMAX - len(qs))
                return (f"### Answer key ({len(qs)} questions)", *fbs)

            gen_btn.click(_on_generate, [n_slider, quiz_topic],
                          [quiz_title, quiz_state] +
                          [x for pair in zip(q_md, q_radio, q_fb) for x in pair])
            check_btn.click(_on_check, [quiz_state] + q_radio, [score_md] + q_fb)
            reveal_btn.click(_on_reveal, quiz_state, [score_md] + q_fb)

        demo.load(lambda: _choices(assistant), None, remove_dd)
        demo.load(lambda: _choices(assistant), None, topic_dd)
        demo.load(lambda: _choices(assistant), None, quiz_topic)
        demo.load(lambda: _to_rows(assistant.list_documents()), None, doc_table)
        gr.Markdown(PRIVACY)

    return demo


def main() -> None:
    assistant = CourseAssistant()
    build(assistant).launch(server_name="127.0.0.1", server_port=7580)


if __name__ == "__main__":
    main()
