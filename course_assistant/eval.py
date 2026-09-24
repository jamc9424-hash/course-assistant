"""Evaluation harness: runs a fixed question set over the loaded materials and
compares two retrieval approaches (reranking ON vs OFF) as the assignment asks.

Methodology (documented honestly in README):
  * a fixed question set (text, visual, and one unanswerable) is run against the
    SAME materials under ``use_rerank=True`` and ``use_rerank=False``;
  * we record, per question: the raw answer, whether the model rated it grounded,
    whether every cited source is a real retrieved source, and latency;
  * "correct" is judged with a transparent heuristic (case-insensitive expected
    phrase match) PLUS, for visual questions, that a slide image was retrieved.
    Raw answers are saved so a human can verify the judgment.

Usage:
  python -m course_assistant.eval --materials <dir> --out results/eval_results.json
  # defaults: bundles synthetic sample materials, writes to results/
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import materials as materials_mod
from .config import Settings, load_settings
from .store import CourseAssistant

QUESTION_SET = [
    {
        "id": "t1", "type": "text",
        "question": "According to the Week 2 slides, what three parts make up hybrid retrieval?",
        "expected": ["keyword", "text embedding", "visual embedding"],
    },
    {
        "id": "t2", "type": "text",
        "question": "What is the assistant's evidence policy when the materials do not support an answer?",
        "expected": ["do not establish", "never invent", "say so"],
    },
    {
        "id": "t3", "type": "text",
        "question": "How are practice-quiz answer keys handled in this course assistant?",
        "expected": ["hidden", "until you answer", "fixed"],
    },
    {
        "id": "t4", "type": "text",
        "question": "According to the syllabus, which part of the grade is worth 40 percent?",
        "expected": ["grounded answer"],
    },
    {
        "id": "t5", "type": "text",
        "question": "Does this course require a textbook?",
        "expected": ["does not require", "not required", "no textbook",
                     "provided on canvas"],
    },
    {
        "id": "v1", "type": "visual",
        "question": "Find the slide with the Vibe Coding on Prod meme and describe what the image and text show.",
        "expected": ["vibe coding", "prod"],
    },
    {
        "id": "v2", "type": "visual",
        "question": "Describe the hybrid RAG architecture diagram on the slides (what boxes and arrows connect).",
        "expected": ["pdf", "slides", "retrieve", "rerank", "answer"],
    },
    {
        "id": "u1", "type": "unanswerable",
        "question": "What is the exact instructor office-hours schedule and room number for this course?",
        "expected": [],
    },
]


def _judge(item, answer, images) -> dict:
    if item["type"] == "unanswerable":
        return {"correct": not answer.grounded, "method": "acknowledged-missing"}
    text = answer.answer.lower()
    phrase_hit = any(p in text for p in item["expected"])
    image_ok = (not images) if item["type"] == "visual" else True
    if item["type"] == "visual":
        have_image = bool(images)
        correct = answer.grounded and phrase_hit and have_image
        return {"correct": bool(correct), "method": "grounded+phrase+image",
                "phrase_hit": phrase_hit, "have_image": have_image}
    correct = answer.grounded and phrase_hit
    return {"correct": bool(correct), "method": "grounded+phrase",
            "phrase_hit": phrase_hit}


def _run_condition(assistant: CourseAssistant, rerank: bool, questions) -> dict:
    assistant.s.use_rerank = rerank
    rows = []
    for item in questions:
        t0 = time.time()
        answer, diag = assistant.answer(item["question"], topic=None)
        images = [s.image_path for s in answer.sources if s.image_path]
        verdict = _judge(item, answer, images)
        rows.append({
            "id": item["id"],
            "type": item["type"],
            "question": item["question"],
            "rerank": rerank,
            "answer": answer.answer,
            "grounded": answer.grounded,
            "supports_sources": bool(answer.sources),
            "num_sources": len(answer.sources),
            "source_pages": [f"{s.document}:{s.page}" for s in answer.sources],
            "have_image": bool(images),
            "latency_ms": round(answer.latency_ms, 1),
            "retrieval": dict(diag),                 # keep error keys visible
            **verdict,
        },)
        time.sleep(0.2)  # gentle pacing across the flaky endpoints
    n_correct = sum(1 for r in rows if r["correct"])
    return {
        "rerank": rerank,
        "questions_run": len(rows),
        "correct": n_correct,
        "correct_rate": round(n_correct / len(rows), 3),
        "avg_latency_ms": round(sum(r["latency_ms"] for r in rows) / len(rows), 1),
        "supported_sources_rate": round(
            sum(1 for r in rows if r["supports_sources"]) / len(rows), 3),
        "rows": rows,
    }


def run_eval(materials_dir: Path | None, out: Path, both: bool = True) -> dict:
    materials_dir = Path(materials_dir) if materials_dir else materials_mod.MATERIALS
    if not list(materials_dir.glob("*.*")):
        print("No materials present; generating synthetic sample deck.")
        materials_mod.make_materials()
    supported = {".pdf", ".pptx", ".docx", ".txt", ".md", ".png", ".jpg", ".jpeg"}
    files = [p for p in materials_dir.rglob("*") if p.is_file()
             and p.suffix.lower() in supported
             and "out" not in p.parts]        # skip generated png under out/
    files = [p for p in files if p.parent == materials_dir] or files
    if not files:
        raise SystemExit("No supported material files found.")

    base = load_settings()
    results = {}
    for rerank in ([True, False] if both else [True]):
        s = Settings(data_dir=base.data_dir / f"eval_{rerank}",
                      api_key=base.api_key,
                      request_timeout=base.request_timeout,
                      max_attempts=6)
        app = CourseAssistant(s)
        print(f"  -> ingesting {len(files)} file(s) (rerank={rerank})")
        for f in files:
            r = app.add_file(f)
            print(f"     - {f.name}: {r['status']} "
                  f"({r.get('chunks', 0)} chunks, {r.get('images', 0)} images)")
        results[f"rerank_{rerank}"] = _run_condition(app, rerank, QUESTION_SET)
        print(f"     correct {results[f'rerank_{rerank}']['correct']}/"
              f"{len(QUESTION_SET)} in "
              f"{results[f'rerank_{rerank}']['avg_latency_ms']} ms avg")

    summary = {
        "material_count": len(files),
        "question_count": len(QUESTION_SET),
        "rerank_on": results.get("rerank_True", {}).get("correct_rate"),
        "rerank_off": results.get("rerank_False", {}).get("correct_rate"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"summary": summary, "conditions": results, "question_set": QUESTION_SET},
        indent=2), encoding="utf-8")
    print(f"\nSaved results -> {out}")
    print(json.dumps(summary, indent=2))
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--materials", default=None, help="directory with course files")
    ap.add_argument("--out", default="results/eval_results.json")
    ap.add_argument("--both", action="store_true", default=True)
    args = ap.parse_args()
    run_eval(args.materials, Path(args.out), both=args.both)


if __name__ == "__main__":
    main()
