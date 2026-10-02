# Assignment 2 evaluation record

This evaluation was run locally against the five permitted lecture decks supplied outside the repository. The decks and generated artifacts are not committed to the public repository. The run extracted **142 slide records** from **142 slides** and used the same ten questions for both retrieval configurations.

## Question set and results

| ID | Question | Keyword baseline | Offline hybrid fallback |
|---|---|---:|---:|
| Q1 | What is the most useful way to select an LLM for a business application? | Missed expected-term check | Missed expected-term check |
| Q2 | As a conversation grows longer, what happens to model accuracy? | Correct/supporting sources | Correct/supporting sources |
| Q3 | What is quantization? | Correct/supporting sources | Correct/supporting sources |
| Q4 | Which prompt change most directly improves inconsistent customer-feedback classification? | Missed expected-term check | Missed expected-term check |
| Q5 | Why break a complex coding task into smaller sequential steps? | Correct/supporting sources | Correct/supporting sources |
| Q6 | What is the relationship between Git and GitHub? | Correct/supporting sources | Correct/supporting sources |
| Q7 | What is the central difference between RAG and fine-tuning? | Correct/supporting sources | Correct/supporting sources |
| Q8 | What capabilities does image Q&A provide? | Correct/supporting sources; no image displayed | Correct/supporting sources; no image displayed |
| Q9 | What does the Week 2 “Vibe Coding on Prod” slide communicate? | Correct/supporting sources; no image displayed | Correct/supporting sources; no image displayed |
| Q10 | What information is absent from these lecture decks about the final project deadline? | Failed missing-information check | Failed missing-information check |

The detailed machine-readable record, including returned document/slide locations and latency, is in [`evaluation-results.json`](evaluation-results.json).

## Comparison protocol

The same five decks and ten questions were run through:

1. **Keyword baseline:** dependency-light BM25-style text retrieval.
2. **Offline hybrid fallback:** the application’s keyword retrieval plus separate visual-index path, with no remote embeddings or reranking because no class credential was loaded in the evaluation environment.

### Aggregate results

| Configuration | Expected-term checks | Sources returned for supported questions | Visual evidence displayed | Mean retrieval latency |
|---|---:|---:|---:|---:|
| Keyword baseline | 7/10 | 9/10 | 0/10 | 0.172 ms |
| Offline hybrid fallback | 7/10 | 9/10 | 0/10 | 0.167 ms |

The expected-term check is a repeatable lexical check, not a substitute for human grading. “Sources returned” means the retriever returned evidence; source quality still requires human review.

## Interpretation

The offline hybrid fallback did not improve the results because the class text-embedding, visual-embedding, and multimodal-reranking services were not configured, and LibreOffice was unavailable for rendering PPTX slide images. The keyword baseline therefore remains the verified local reliability path. A live comparison with the class services is still required before claiming that embeddings and reranking improve answer quality or visual-slide recall.

## Investigated limitation

Q10 exposed a missing-information weakness in the original evaluation run: the retriever returned unrelated Week 5 slides instead of returning no evidence for a final-project-deadline question. After that run, the answer path was hardened with a relevance-overlap abstention check and a regression test (`test_unanswerable_query_with_partial_keyword_overlap_abstains`). The saved JSON remains the original run record; rerun the permitted-deck benchmark to replace its historical Q10 result.

The Q8 and Q9 visual cases also returned the expected slide locations from extracted PPTX text, but no original slide image was displayed in this run. LibreOffice conversion and the live visual embedding/parser services must be enabled for the complete visual-evidence acceptance check.
