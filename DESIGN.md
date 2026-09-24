# Design Note — Course Assistant (team/oliver-wip)

*Author: Oliver (via agent), branch `team/oliver-wip`.*

This note records the verified service contracts, the chosen architecture, the
designs I built, and the comparison I performed. It is the reasoning behind the
README report.

## 1. Verified class-service contracts

All five class services live on `dobolyi.com` (ports 9001–9005), are protected
by a shared `CLASS_SERVICE_API_KEY`, and publish an OpenAPI spec at
`/openapi.json`. I verified every contract below with a live request, not from
docs alone.

| Port | Role (this branch) | Model served | Verified contract |
|------|--------------------|--------------|-------------------|
| 9001 | Vision-capable LLM | `cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit` | OpenAI `POST /v1/chat/completions`. **Reasoning model**: sets `thinking_token_budget: 0` so `content` is populated deterministically (otherwise `content` is `null` and the draft sits in `reasoning`). |
| 9002 | Text embeddings | `nvidia/Nemotron-3-Embed-1B-BF16` | OpenAI `POST /v1/embeddings`, `input` = string/array of strings. Returns `data[].embedding`, **dim 2048**. |
| 9003 | Visual embeddings | `Qwen/Qwen3-VL-Embedding-2B` | `POST /v1/embeddings` but the **chat variant** (`messages` + `image_url` data-URL) is required for images; also accepts text. Returns `data[].embedding`, **dim 2048**. |
| 9004 | Multimodal reranker | `Qwen/Qwen3-VL-Reranker-2B` | Cohere-style `POST /v1/rerank` with `query`, `documents`, `top_n`. Returns `results[{index, relevance_score, document}]`. Query **and** each doc may be `{"text": …}` or multimodal `{"content":[{type:"image_url",…}]}`. |
| 9005 | Document parser (OCR) | `dots.mocr` | OpenAI `POST /v1/chat/completions` with an image part returns extracted text/markdown. Used as an OCR fallback for scanned/image-based pages. |

**Important gitignored note:** The canonical key used for service calls is
discussed with the team; the code reads it from `.env` / environment
(`CLASS_SERVICE_API_KEY`) and never hard-codes or commits it.

## 2. Config strategy (secrets-safe)

- All endpoints + key come from environment variables, loaded from a local
  `.env` file (gitignored) via `python-dotenv`-style parsing implemented
  ourselves (no extra dep) or `os.environ`.
- `.env.example` documents **dummy** values and the *correct* port mapping
  (fixed from the scaffold's placeholder mapping, which was misleading).
- Keys are never in source, browser code, logs, docs, screenshots, tests, or
  the repository.

## 3. Architecture

Assets (PDF/PPTX/DOCX/TXT/MD) -> **parse/render** (PyMuPDF text + page PNGs;
python-pptx/python-docx text; OCR fallback via 9005) ->

- **text chunks** carrying source metadata (doc_id, page, section, excerpt)
- **visual records** (one per page/slide) carrying the rendered PNG

Three independent indexes, kept separate as required:

1. **Keyword** — BM25 (bm25s) over text chunks.
2. **Text vector** — cosine similarity over text-embedding vectors (:9002).
3. **Visual vector** — cosine similarity over visual-embedding vectors (:9003)
   for page/slide images (also used to retrieve slide images for display).

**Hybrid merge:** results from the three retrievers are merged by
reciprocal-rank-fusion (RRF) into candidates.

**Rerank:** optional reranking of candidates with :9004 (multimodal; query +
text excerpts, and if a candidate is visual, the slide image).

**Answer generation:** the vision LLM (:9001) receives the top chunks + the
top slide image + the question, and is prompted to return **structured JSON**
with separate `answer` and `sources` fields, citing doc/page/section with an
excerpt, and to explicitly state when the materials do not establish an answer.

**Validation:** responses are schema-validated (JSON parse + required fields);
a *source-support check* verifies each cited source string actually appears in
the retrieved evidence. If the model cannot ground an answer, we surface a
"materials do not establish this" response with no fabricated citation.

**Quiz generation:** the LLM produces fixed multiple-choice questions with a
stable answer key (seeded/`temperature=0`); solutions are stored separately and
only revealed after the student answers or requests the answer. Scores are
computed from the stored key, not re-generated.

## 4. Document management

- Add: hash file content -> dedupe (same hash = already present, no duplicate
  ingest). Each indexed doc gets a content-addressed id.
- Remove: deletes the doc's text chunks, visual records, and vectors from all
  indexes so later answers cannot rely on it.
- Supported formats and conversion steps are documented in README; PDF is fully
  native (render + OCR), PPTX/DOCX text is extracted natively, and slide/print
  images for those require a manual PDF export or LibreOffice (documented as a
  limitation since LibreOffice is not guaranteed on target machines).

## 5. Config knobs

`ANSWER`, quiz, rerank-on/off, chunk size / overlap (for the comparison),
top-k per retrieve, federation weights, and which services are enabled (so
unavailable services degrade gracefully).

## 6. Comparison to run (per assignment)

Rerank **off vs theoretical** — because the live reranker is fast and reliable,
the more meaningful design comparison for this branch is:

- **A:** text-topk + visual-topk, RRF merge, **BM25 no rerank** (keyword-only
  hybrid, no neural reranker).
- **B:** BM25 + text + visual, RRF merge, then **rerank with :9004**.

Recorded on the same fixed set of eval questions and same files: correct vs not,
sources-supported vs not, latency. Keep the approach that is both accurate and
grounded without a large latency cost.

*(This design note is a living document — update it when the team chooses a
design based on our comparison, before merging to `main`.)*
