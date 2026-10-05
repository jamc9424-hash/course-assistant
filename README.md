# Course Assistant

A Python course assistant that answers questions and generates practice quizzes from course materials downloaded from Canvas.

## Project goal

Build a grounded, multimodal course assistant that:

- accepts course files such as PDF, PPTX, PPT, ODP, DOCX, and common text formats;
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

The final merged implementation is on `main`. PR #7 is merged and its CI checks passed. The repository retains historical branches for team work. The current public audit found no peer-review records for the earlier integration, issues 1–6 remain open, and `main` is not branch-protected; these are collaboration-process limitations, not claims of completed review.


## Architecture at a glance

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
                                                  Python Gradio interface
```

The class service map is documented in [`docs/class-services.md`](docs/class-services.md). The integrated services use ports 9001–9005: 9001 now provides grounded generative vision answers, while 9002–9005 provide text embeddings, multimodal embeddings, reranking, and document parsing. Credentials are intentionally not stored here and must be supplied through server-side environment variables or an ignored local configuration file.

## Local setup

From a fresh clone:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
pip install -r requirements-optional.txt  # file parsing and Gradio UI
pytest
```

Launch the interface with:

```bash
python -m course_assistant.app
```

Copy `.env.example` to `.env`, replace only the dummy API key locally, and load the variables into the server process before launch. On macOS/Linux/Git Bash use `set -a; source .env; set +a`. In PowerShell, use `Get-Content .env | Where-Object { $_ -and -not $_.StartsWith('#') } | ForEach-Object { $name,$value = $_ -split '=',2; Set-Item -Path "Env:$name" -Value $value }`. On Render, add the variables under the service's Environment settings and mark `CLASS_SERVICE_API_KEY` as a secret; do not place the value in `render.yaml`. Endpoint names, models, and request formats are listed in [`docs/class-services.md`](docs/class-services.md). The real class API key must never be placed in source, browser code, logs, screenshots, documentation, test results, or GitHub. The supplied class endpoints use HTTP; set `CLASS_SERVICE_ALLOW_INSECURE_HTTP=true` only on the trusted class network. Use HTTPS for production whenever available.

## Supported input policy

The upload manager accepts PDF, PPTX, PPT, ODP, DOCX, TXT, and Markdown. PDF files are rendered page-by-page into original page images. PPTX files are parsed directly and, when LibreOffice/`soffice` is installed, converted to PDF so original slide images are preserved. Legacy PPT and ODP files require LibreOffice for conversion. Without LibreOffice, export slides to PDF before upload. Unsupported or malformed files receive a clear error without partial searchable content.

In the app, upload files through **Add course materials**. The uploaded-material list shows each content ID. Enter that ID under **Remove document** to remove its chunks and generated artifacts from the active session. Identical file content is skipped on repeat upload.

## Use the app

1. Launch with `python -m course_assistant.app` and open the local Gradio URL shown in the terminal, normally `http://127.0.0.1:7860`.
2. In **Add course materials**, upload one or more supported files. The interface reports duplicate uploads and displays each document ID.
3. To remove a document, copy its ID into **Document ID to remove** and select **Remove document**. The document's chunks and generated images are deleted from the active session.
4. In **Ask a question**, optionally filter by material/topic, enter a specific question, and select **Ask Course Assistant**. Read the answer and numbered source excerpts together; visual sources include their original page image. Internally the API retains separate `answer` and `sources` fields.
5. In **Practice quiz**, select a count, choose answers with the on-screen radio buttons, then select **Check answers**. Solutions remain hidden until submission or explicit reveal. With the class vision service configured, the app requests source-anchored conceptual questions; without it, the offline mode derives focused subject–relation questions from explicit source sentences, rejects near-duplicate or same-subject distractors, and refuses when the evidence cannot support a distinct answer. This is a limited rule-based exercise, not a substitute for human-reviewed pedagogy.
6. Rerun the automated checks with `pytest`, or separately with `pytest -m "not e2e" -q` and `pytest -m e2e -q`.

## Deployment

The included `Dockerfile` and `render.yaml` support a Render deployment. The image installs LibreOffice Impress so uploaded presentations can be rendered as slide images. Supply `CLASS_SERVICE_API_KEY` through Render's secret environment settings; never put it in `render.yaml` or the image. Render supplies `PORT`; the app binds to `GRADIO_SERVER_NAME=0.0.0.0`. Configure the endpoint/model variables from `.env.example` when using non-default services. Use HTTPS service URLs in production; set `CLASS_SERVICE_ALLOW_INSECURE_HTTP=true` only for a trusted network using the supplied HTTP endpoints. This repository contains deployment packaging, not a completed hosted deployment; a public deployment URL must be recorded only after a real smoke test.

## Evidence policy

Every answer and quiz explanation must carry structured source records. A source record should identify the document, page/slide or section, a text excerpt or image reference, and enough metadata to reproduce the evidence. If retrieval does not support an answer, the assistant must say that the materials do not establish it.

## Evaluation and status

The current merged behavior hides quiz source excerpts until answer/reveal, abstains when a text-only query has insufficient evidence overlap, and defaults insecure HTTP access to disabled. These behaviors are covered by regression tests in the final branch.


The implemented baseline is tested locally and documented in `docs/evaluation.md`. The supplied decks were evaluated with ten repeatable questions using the keyword baseline and offline hybrid fallback; aggregate results and returned slide locations are in `docs/evaluation-results.json`. That JSON is the original benchmark record and retains the historical pre-remediation Q10 failure; the current merged code includes the abstention fix and regression test, but the permitted-deck benchmark must be rerun before claiming post-fix quality results. A live comparison with class embeddings/reranking and original-slide visual recall remains pending until authorized course materials, credentials, and the optional rendering stack are available.

## Integrated implementation

The integrated app combines JamesBranch's verified material management, hybrid retrieval, visual evidence, structured answers, quiz controls, service fallbacks, security checks, and automated tests with EliasBranch's LibreOffice presentation rendering, upload-size guard, deployment packaging, and responsive port configuration.

For a dependency-light question-answering smoke test:

```bash
PYTHONPATH=src python -m course_assistant.cli notes.txt --question "What does the material say?"
```

The implementation provides:

- PDF, PPTX, PPT, ODP, DOCX, TXT, and Markdown ingestion paths;
- PDF page and optional LibreOffice-rendered presentation image preservation with source page/slide metadata;
- separate keyword, local text-embedding, and visual-embedding indexes, with optional class-service embeddings and multimodal reranking;
- structured answers with `answer` and `sources` fields;
- missing-information responses when retrieval finds no supporting evidence;
- material/topic filtering and deterministic multiple-choice quizzes with fixed answer keys;
- hidden quiz solutions until the quiz taker answers a question or explicitly requests its solution; answered feedback includes the score, correct/selected choice, explanation, and supporting source;
- Gradio question-answering and quiz/scoring interface.
- Session-scoped upload and removal controls with SHA-256 content deduplication; removing a document rebuilds the searchable corpus and deletes generated artifacts.
- Visual RAG returns retrieved slide images with document and page/slide captions. When the parser service is available, visual sources also receive a conservative description of visible pictures, memes, diagrams, and charts.

The upload manager accepts PDF, PPTX, PPT, ODP, DOCX, TXT, and Markdown. Unsupported formats are rejected without entering the store, parser failures are reported without leaving partial artifacts, and re-uploading identical bytes is skipped even if the filename changes. Uploads are capped at 150 MB.

The baseline runs without class credentials using keyword retrieval plus deterministic hashed token/ngram indexes (these are **not semantic embeddings**). When `CLASS_SERVICE_API_KEY` is present in the ignored local environment and HTTP is explicitly permitted on a trusted network, the assistant can use 9001 for grounded multimodal answers and conceptual quiz drafting, 9002 for text embeddings, 9003 for visual embeddings, 9004 for multimodal reranking, and 9005 for visual parsing. Search rejects zero/negative vector matches, source IDs in model answers must be in range, and unsupported numerical claims fall back to extractive evidence. The offline path cannot explain a scanned image with no extracted text; it abstains instead. See [`docs/evidence-first-evaluation.md`](docs/evidence-first-evaluation.md) for measured checks and remaining quality gaps.

## Architecture diagram

![Hybrid multimodal RAG architecture](docs/architecture.svg)

The SVG matches the implemented flow: upload and deduplicate material, parse text and PDF page images, maintain separate keyword/text/visual indexes, merge and rerank candidates, validate source support, then display answers, sources, slide images, and quizzes.

## Evaluation report

The assignment question set, comparison protocol, saved results, and investigated limitations are in [`docs/evaluation.md`](docs/evaluation.md) and [`docs/evaluation-results.json`](docs/evaluation-results.json). The ten-question run includes two visual cases, including the required Week 2 “Vibe Coding on Prod” case. Its visual image checks remain pending because this local run lacked LibreOffice and class visual services. The manual and automated verification checklist is in [`docs/manual-verification.md`](docs/manual-verification.md).

## Screenshots

These **historical** screenshots were captured from commit `4587e42` using a synthetic, non-course demo PDF. They do not depict the redesigned radio-button practice flow or establish quality on course material. Replace them with new permitted-material captures after an actual live evaluation.

### Answer with retrieved slide

![Course Assistant answer with retrieved slide](docs/screenshots/answer-with-slide.png)

### Quiz feedback with source

![Course Assistant quiz feedback with source](docs/screenshots/quiz-feedback.png)

## Current findings and limitations

- The integrated answer path can now use the class vision-capable Qwen3.6 service for grounded text-and-image synthesis, while retaining a tested local fallback when the service is unavailable.
- The retrieval stack is ready for stronger semantic and multimodal recall through Nemotron text embeddings, Qwen3-VL embeddings, and Qwen3-VL reranking; the dependency-light keyword path remains available for offline use.
- PPT/PPTX/ODP image rendering depends on LibreOffice; without it, PPTX text and source locations still work and manual PDF export is supported.
- The quiz generator is a deterministic baseline for evaluating retrieval and evidence behavior, with stable keys and source-backed feedback; a richer pedagogical writer can be added without changing the evidence contract.
- Automated tests cover the dependency-light core, security configuration, source validation, answer-key stability, and service request construction. Live service calls are not run in CI.

## License

TBD by the project team.
