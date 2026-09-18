# Evaluation record

## Branch

`JamesBranch` implements the dependency-light vertical slice first, then adds optional class-service retrieval behind the same interface.

## Design comparison

| Choice | Baseline | Optional service path | Current finding |
|---|---|---|---|
| Initial retrieval | Dependency-free BM25-style keyword index | Nemotron text embeddings plus Qwen visual embeddings | Baseline is reproducible offline; service path is wired but needs permitted course fixtures for quality comparison |
| Candidate ranking | Score merge across separate text/visual indexes | Score merge followed by Qwen multimodal reranking | Live endpoint contracts were verified; ranking quality remains unchecked without a benchmark set |
| Answer generation | Extractive answer from supporting excerpts | Same conservative evidence boundary | Prevents unsupported claims while the supplied generation endpoint remains unspecified |

## Repeatable checks

```bash
uv run --with pytest pytest -q
python -m compileall -q src
```

The current suite checks ingestion metadata, text/visual index separation, source-support validation, missing-information behavior, fixed quiz keys, secure service request construction, and repository hygiene.

## Not yet checked

- Retrieval recall and reranking accuracy on real Canvas slides, diagrams, and charts
- Latency and failure behavior against all services during a complete ingest/query session
- PPTX/DOCX visual rendering fidelity
- Gradio interaction tests and production screenshots
- Answer quality from a vision-capable generation service; no generation endpoint was provided in the current endpoint set
