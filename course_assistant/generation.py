"""Answer and quiz generation over retrieved evidence.

Both generation paths:
  * use the class vision LLM (9001) at temperature 0 for stable output,
  * ask for structured JSON (separate ``answer`` / quiz fields),
  * are schema-validated, and
  * ground citations in the *actually retrieved* evidence (source-support
    check = the model may only cite evidence indices we handed it).
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Optional

from .retrieval import Evidence
from .service import ServiceError, VisionLLMClient
from .types import Answer, QuizQuestion, Source

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def _image_data_url(image_path: str) -> str:
    low = image_path.lower()
    mime = "image/jpeg" if (low.endswith(".jpg") or low.endswith(".jpeg")) else "image/png"
    b64 = base64.b64encode(open(image_path, "rb").read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


class GenerationError(RuntimeError):
    pass


def _extract_json(text: str) -> Any:
    """Parse the first top-level JSON value (object or array) in *text*.

    Uses a balanced scan so arrays and nested objects survive surrounding prose,
    markdown fences, or an API that returns the body verbatim.
    """
    start = -1
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start == -1:
        raise GenerationError("model returned no JSON structure")

    depth = 0
    in_str = False
    esc = False
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        raise GenerationError("model returned unbalanced JSON")
    candidate = text[start:end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise GenerationError(f"model returned malformed JSON: {e}") from e


def _evidence_prompt(evidence: list[Evidence]) -> str:
    lines = []
    for i, ev in enumerate(evidence):
        src = ev.source
        if src is None:
            lines.append(f"[{i}] source: (no provenance)")
            continue
        loc = src.document
        page = f", page {src.page}" if src.page else ""
        section = f" ({src.section})" if src.section else ""
        excerpt = (src.excerpt or "")
        kind = "image" if ev.kind == "visual" else "text"
        lines.append(
            f"[{i}] {kind} source: {loc}{page}{section}\n    excerpt: {excerpt[:500]}"
        )
    return "\n".join(lines) if lines else "(no evidence retrieved)"


def _source_from(evidence: list[Evidence], idx: int, excerpt_limit: int = 400) -> Source:
    src = evidence[idx].source
    return Source(
        document=src.document if src else "unknown",
        page=src.page if src else None,
        section=src.section if src else None,
        excerpt=(src.excerpt or "")[:excerpt_limit] if src else None,
        image_path=src.image_path if src else None,
    )


class AnswerGenerator:
    def __init__(self, llm: VisionLLMClient):
        self.llm = llm

    def _visual_images(self, evidence: list[Evidence], cap: int = 3) -> list[str]:
        seen = set()
        out = []
        for ev in evidence:
            p = (ev.source.image_path if ev.source else None)
            if p and p not in seen:
                seen.add(p)
                out.append(p)
            if len(out) >= cap:
                break
        return out

    def build_prompt(self, question: str, evidence: list[Evidence],
                     instructions: str = "") -> list[dict]:
        ev = _evidence_prompt(evidence)
        sys_msg = (
            "You are a grounded course assistant. Answer ONLY from the numbered "
            "evidence sources and any attached slide images. When an attached "
            "image (a slide, diagram, chart, or meme) is relevant, base your "
            "description of it on what the image actually shows. Cite evidence "
            "by index. If the evidence does not establish the answer, say the "
            "course materials do not establish it and set grounded=false; never "
            "invent facts or citations.\n"
            "Return ONLY a JSON object of the form:\n"
            '{"answer": "<answer text>", "used_source_indices": [int, ...], '
            '"grounded": true|false, "confidence": 0.0..1.0, "note": '
            '"<short caveat or the string \\"\\">"}'
        )
        text = (f"QUESTION:\n{question}\n\nEVIDENCE:\n{ev}\n\n"
                f"INSTRUCTIONS:\n{instructions}")
        images = self._visual_images(evidence)
        if images:
            # attach the actual slide images so the vision model can see them
            content: list[dict[str, Any]] = [{"type": "text", "text": text}]
            for p in images:
                content.append({"type": "image_url",
                                "image_url": {"url": _image_data_url(p)}})
            user: dict[str, Any] = {"role": "user", "content": content}
        else:
            user = {"role": "user", "content": text}
        return [
            {"role": "system", "content": sys_msg},
            user,
        ]

    def generate(self, question: str, evidence: list[Evidence],
                 instructions: str = "") -> Answer:
        t0 = time.time()
        if not evidence:
            return Answer(
                answer="The course materials do not establish an answer to this "
                       "question (no relevant material was retrieved).",
                grounded=False, supports_sources=False, sources=[],
                note="no retrieved evidence",
                latency_ms=(time.time() - t0) * 1000,
            )
        prompt = self.build_prompt(question, evidence, instructions)
        try:
            raw = self.llm.chat(prompt, max_tokens=700)
        except ServiceError as e:
            raise GenerationError(str(e)) from e
        payload = _extract_json(raw)
        used = payload.get("used_source_indices", [])
        # source-support check: only indices within the evidence we handed over
        used = [int(i) for i in used if isinstance(i, int)]
        used = [i for i in used if 0 <= i < len(evidence)]
        sources = [_source_from(evidence, i) for i in used]
        grounded = bool(payload.get("grounded", True))
        return Answer(
            answer=str(payload.get("answer", "")).strip(),
            sources=sources,
            grounded=grounded,
            confidence=float(payload.get("confidence", 0.0)),
            note=payload.get("note") or None,
            latency_ms=(time.time() - t0) * 1000,
        )


class QuizGenerator:
    def __init__(self, llm: VisionLLMClient):
        self.llm = llm

    def generate(self, evidence: list[Evidence], n: int = 4,
                 topic: Optional[str] = None) -> list[QuizQuestion]:
        ev = _evidence_prompt(evidence)
        subject = f"topic: {topic}" if topic else "the course materials"
        sys_msg = (
            "You are creating fixed-answer multiple-choice practice quizzes from "
            "the numbered evidence sources below. Every question must be "
            "answerable from at least one numbered evidence source. Cite the "
            "supporting evidence index(s) for each question.\n"
            "Return ONLY a JSON array of objects like:\n"
            '[{"question": "...", "options": ["A","B","C","D"], '
            '"correct_index": 0, "explanation": "...", '
            '"used_source_indices": [int], "grounded": true|false}]'
        )
        user = (
            f"Create {n} multiple-choice questions about {subject}, each with "
            f"exactly 4 options and one correct index, using evidence below.\n\n"
            f"EVIDENCE:\n{ev}"
        )
        raw = self.llm.chat(
            [{"role": "system", "content": sys_msg},
             {"role": "user", "content": user}],
            max_tokens=1500,
        )
        data = _extract_json(raw)
        if isinstance(data, dict) and "questions" in data:
            data = data["questions"]
        questions: list[QuizQuestion] = []
        for i, item in enumerate(data if isinstance(data, list) else []):
            options = item.get("options", [])
            if len(options) < 2:
                continue
            correct = int(item.get("correct_index", 0))
            correct = max(0, min(correct, len(options) - 1))
            used = [int(x) for x in item.get("used_source_indices", [])
                    if isinstance(x, int) and 0 <= x < len(evidence)]
            sources = [_source_from(evidence, i, excerpt_limit=300) for i in used]
            grounded = bool(item.get("grounded", True))
            if not grounded:
                continue  # don't emit questions the evidence doesn't support
            questions.append(
                QuizQuestion(
                    id=f"q{i:02d}",
                    question=str(item.get("question", "")).strip(),
                    options=[str(o) for o in options],
                    correct_index=correct,
                    explanation=str(item.get("explanation", "")).strip(),
                    sources=sources,
                )
            )
        return questions
