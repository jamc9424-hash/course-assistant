# Course Assistant

A Python course assistant that answers questions and generates practice quizzes from course materials downloaded from Canvas.

## Project goal

Build a grounded, multimodal course assistant that:

- accepts course files such as PDF, PPTX, DOCX, and common text formats;
- preserves extracted text, source locations, and original page/slide images;
- answers questions with hybrid retrieval using keyword, text-embedding, and visual-embedding search;
- acknowledges missing information instead of inventing answers or citations;
- generates fixed-answer multiple-choice quizzes with scores and explanations;
- shows document/page/slide/section references with supporting excerpts or screenshots.

## Collaboration model

This repository is intentionally set up for parallel alternatives:

1. Start from `main`.
2. Create one branch per design, for example `team/<name>-baseline`.
3. Keep changes scoped and include automated checks.
4. Open a pull request describing tradeoffs, test results, and limitations.
5. Compare branches against the same evaluation checklist before selecting a foundation.
6. The selected implementation will be extended on `main` after review.

Do not commit course files, API keys, endpoint credentials, generated indexes, or student data.

## Planned architecture

```text
Canvas files
  -> parser / page-slide renderer
  -> text chunks + source metadata       visual page/slide records
  -> keyword index + text vector index  visual vector index
                  \                    /
                   candidate merge + multimodal reranking
                                |
                 answer or quiz generation with evidence
                                |
                 schema validation + source-support checks
                                |
                         Python interface (planned Gradio)
```

The class service map is documented in [`docs/class-services.md`](docs/class-services.md). The four supplied services use ports 9002–9005; endpoint adapters must follow the model cards and vLLM 0.29.0 conventions. Credentials are intentionally not stored here and must be supplied through server-side environment variables or an ignored local configuration file.

## Local setup

The implementation is being developed incrementally. The expected setup is:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Use dummy values in examples. Never place real keys in source, browser code, logs, screenshots, documentation, or test artifacts.

## Supported input policy

The finished app will document its tested formats explicitly. The target set is PDF, PPTX, DOCX, TXT, and Markdown, with page/slide rendering where the format supports it. Unsupported or malformed files should receive a clear error rather than partial, untraceable ingestion.

## Evidence policy

Every answer and quiz explanation must carry structured source records. A source record should identify the document, page/slide or section, a text excerpt or image reference, and enough metadata to reproduce the evidence. If retrieval does not support an answer, the assistant must say that the materials do not establish it.

## Evaluation and status

The project is currently in repository setup. Add benchmark materials only when permitted by the course. Each design comparison should record:

- retrieval configuration and model/service versions;
- latency and failure behavior;
- grounded-answer and citation-support checks;
- quiz answer-key stability;
- visual evidence coverage;
- known limitations and unchecked cases.

Screenshots and findings will be added to `docs/` as the interface becomes available.

## JamesBranch implementation

The first vertical slice is available on `JamesBranch`:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
pip install -r requirements-optional.txt  # file parsing and Gradio UI
python -m course_assistant.app
```

For a dependency-light question-answering smoke test:

```bash
PYTHONPATH=src python -m course_assistant.cli notes.txt --question "What does the material say?"
```

The implementation provides:

- PDF, PPTX, DOCX, TXT, and Markdown ingestion paths;
- PDF page image preservation and source page/slide metadata;
- separate keyword and visual indexes, optional text/visual embedding indexes, and reranking adapters;
- structured answers with `answer` and `sources` fields;
- missing-information responses when retrieval finds no supporting evidence;
- material/topic filtering and deterministic multiple-choice quizzes with fixed answer keys;
- hidden quiz solutions until the solution is explicitly requested through the Python API;
- Gradio question-answering and quiz/scoring interface.
- Session-scoped upload and removal controls with SHA-256 content deduplication; removing a document rebuilds the searchable corpus and deletes generated artifacts.
- Visual RAG returns retrieved slide images with document and page/slide captions. When the parser service is available, visual sources also receive a conservative description of visible pictures, memes, diagrams, and charts.

The upload manager accepts PDF, PPTX, DOCX, TXT, and Markdown. Unsupported formats are rejected without entering the store, parser failures are reported without leaving partial artifacts, and re-uploading identical bytes is skipped even if the filename changes.

The baseline runs without class credentials using keyword retrieval. When `CLASS_SERVICE_API_KEY` is present in the ignored local environment, the assistant uses the configured class text embedding, visual embedding, and reranking services. Document parsing is wired through the service client for future image-first ingestion.

## Current findings and limitations

- The live class endpoints were connectivity-tested and their request contracts are documented in `docs/class-services.md`.
- The current answer generator is extractive and conservative; it does not yet call a generative vision-capable LLM because a generation endpoint was not included in the supplied service map.
- PPTX and DOCX preserve text/source locations, but PDF is currently the only parser that renders original page images automatically.
- The quiz generator is a deterministic baseline for evaluating retrieval and evidence behavior, not a final pedagogical question writer.
- Automated tests cover the dependency-light core, security configuration, source validation, answer-key stability, and service request construction. Live service calls are not run in CI.
- No production screenshots or course-material benchmark results are committed yet; those require permitted Canvas materials.

## License

TBD by the project team.
