# Manual verification checklist

Run these checks after installing the optional UI dependencies. The automated suite covers the same workflows without requiring a browser.

## Completed locally

- [x] Upload a supported text fixture.
- [x] Upload the same bytes twice and confirm one material record.
- [x] Ask a supported question and inspect structured sources.
- [x] Generate a quiz with hidden solutions.
- [x] Submit an answer and inspect score, explanation, and source.
- [x] Remove the material and confirm a later answer reports missing information.
- [x] Run the Gradio UI against a synthetic PDF and capture answer/slide and quiz-feedback screenshots.
- [x] Parse the architecture SVG and evaluation JSON.

## Required course-material checks before submission

- [ ] Upload the permitted Week 2 slides and syllabus.
- [ ] Ask for the “Vibe Coding on Prod” meme; verify the displayed slide against the original.
- [ ] Ask about at least one diagram and one chart; verify image and source support.
- [ ] Run the eight-question set through keyword-only and hybrid retrieval paths.
- [ ] Record correctness, citation support, visual-slide recall, and latency in `docs/evaluation-results.json`.
- [ ] Replace synthetic screenshots with permitted course-material screenshots if redistribution is allowed.
- [ ] Check light and dark UI themes for readable controls, source text, and slide images.
- [ ] Repeat selected checks with class services unavailable and confirm keyword fallback.
