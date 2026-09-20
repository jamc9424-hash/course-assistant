# Assignment 2 evaluation record

This evaluation record is committed with the app so another teammate can repeat it. The repository does not contain Canvas course files; uploading copyrighted course material to a public repository is intentionally prohibited. The rows below are the required evaluation set and are marked pending until the team runs them with the permitted Week 2 slides and syllabus.

## Question set

| ID | Question | Required evidence | Status |
|---|---|---|---|
| Q1 | What does the syllabus say about the final project deadline? | Syllabus section/excerpt | Pending course-material run |
| Q2 | How are office hours or instructor contact options described? | Syllabus section/excerpt | Pending course-material run |
| Q3 | What is the main concept introduced in the Week 2 slides? | Slide number + excerpt | Pending course-material run |
| Q4 | What does the diagram on the retrieval slide show? | Actual slide image + slide number | Pending course-material run |
| Q5 | What trend does the chart on the evaluation slide show? | Actual slide image + chart explanation | Pending course-material run |
| Q6 | What does the “Vibe Coding on Prod” meme communicate? | Actual Week 2 slide image + visual description | Pending course-material run |
| Q7 | How does the slide compare the two approaches shown in its visual? | Actual slide image + supporting text | Pending course-material run |
| Q8 | What is the answer to a topic that is absent from the uploaded materials? | Empty sources + missing-information response | Covered by automated tests |

Q4–Q7 are deliberately visual cases. Q6 is the required meme retrieval case.

## Comparison protocol

Run the same question set and the same permitted course files through:

1. **Keyword baseline:** BM25-style keyword retrieval without class-service embeddings or reranking.
2. **Hybrid path:** keyword retrieval plus text embeddings, visual embeddings, and multimodal reranking when the class services are configured.

For every row, record:

- answer correctness: yes/no/partial;
- whether every source supports the answer;
- document and page/slide returned;
- whether the expected image was displayed;
- latency in milliseconds;
- failure or missing-information behavior.

The intended saved-results format is `docs/evaluation-results.json`. Do not commit course files, slide screenshots, API keys, or student data.

## Current automated findings

The dependency-light suite verifies source-support validation, visual source metadata, parser-backed visual descriptions, missing-information behavior, quiz grounding, quiz feedback, upload/removal, duplicate prevention, and model-service fallback. The live course-material comparison is not claimed here because the required Canvas files have not been supplied.

## Interpretation rule

Keep the hybrid path if it improves supported-answer rate or visual-slide recall without unacceptable latency or unsupported citations. Keep the keyword fallback as a reliability path when remote services are unavailable.
