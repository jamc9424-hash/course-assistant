# Evidence-first RAG and practice redesign: verification record

## Why the previous workflow was unreliable

- Vector search returned zero- and negative-similarity records. Those records received reciprocal-rank credit even when unrelated to the query.
- The answer path accepted a model response after a single shared term. It could attach unrelated source records and accept invalid inline citations.
- Sentence-ranking fallback could return a sentence merely sharing the topic while omitting the requested fact (for example, a project evaluation-set sentence for a deadline question).
- Practice MCQs asked which statement about a topic was correct while offering other true statements as distractors. The correct answer was therefore not unique.
- The visible practice interface required JSON answer maps rather than clickable choices, and feedback repeated an entire multi-fact chunk even for a one-sentence question.

## Changed behavior

1. Keyword, text-vector, and image-vector candidate sets remain separate. Zero/negative vector similarities are discarded. Reranking batches encoded image evidence and falls back to fused ranking on malformed/failed scores. Remote visual candidates can be used on scanned image-only pages if the configured model can describe the original image; offline mode refuses unsupported visual claims.
2. The 9001 answer prompt pairs each source excerpt directly with its image. Generated answers must cite valid source numbers and may not introduce numerical facts absent from cited text or a parsed visual description; otherwise the app uses extractive fallback. Sources returned with model answers are limited to cited sources.
3. Common factual intents (deadline, grading weight, cost) abstain when the retrieved evidence never mentions the requested kind of fact. This is a conservative heuristic, not a general entailment proof.
4. Configured 9001 may draft focused conceptual questions using an adjacent source image. Items with malformed schema, unsupported correct answers, duplicate choices, or distractors copied from the same source are rejected. Without the service, exact-source completion questions replace the misleading multi-true-statement MCQ; source feedback is narrowed to the question's sentence. The answer key remains fixed and hidden until submit/reveal.
5. Students use radio choices, not JSON editing. Answers and source excerpts are rendered as readable Markdown; the internal answer contract remains `answer` plus `sources`.

## Reproduction and evidence

Run `PYTHONPATH=src python -m pytest -q` and `python -m compileall -q src`. The latest local run passed **57 tests** and compiled successfully. Tests use synthetic local text and fake service boundaries; no class credential is stored or called. A Gradio-client integration smoke test on port 7861 uploaded synthetic text, returned the office-hours sentence with a numbered citation, abstained on an unsupported final-project deadline, generated two selectable radio questions, graded submitted choices with the matching narrow source sentence, and reset the session. This is workflow evidence, not a course-material quality benchmark.

## Not yet validated

No local `.env` or authorized class material was present for this redesign. A live 9001–9005 probe, evaluation on actual slides, human review of distractor plausibility, and semantic checking of every generated claim remain pending. Exact-substring answer verification and citation checks do **not** establish that a generative explanation is factually entailed by the cited source. The offline mode is intentionally limited to source recall and extractive answers, not a substitute for a semantic model.
