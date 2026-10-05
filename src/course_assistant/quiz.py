from __future__ import annotations

import random
import re
from dataclasses import replace
from typing import Callable, Mapping, Any

from .models import DocumentChunk, Quiz, QuizQuestion, reveal_question

# Offline questions target an atomic subject–relation fact. Distractors come
# from different subjects and never from a near-duplicate answer phrase.
_SPLIT = re.compile(
    r"\b(is|are|was|were|uses|use|shows|show|includes|contains|lists|"
    r"splits|split|combines|connects|decreases|defines|supports|"
    r"identifies|identify|minimizes|estimates|improves|measures|requires|provides)\b",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(r"^\[Visual (?:page|slide) with no extractable text\]$", re.I)


def _content_words(text: str) -> set[str]:
    return {word.casefold() for word in re.findall(r"[A-Za-z0-9]+", text)
            if len(word) > 2 and word.casefold() not in {"the", "and", "for", "with", "using", "what", "which", "when", "where", "does", "did", "are", "how", "why"}}


def _too_similar(left: str, right: str) -> bool:
    a, b = _content_words(left), _content_words(right)
    return bool(a and b and len(a & b) / len(a | b) >= 0.5)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if 25 <= len(part.strip()) <= 300]


def _fact(sentence: str) -> tuple[str, str] | None:
    if _PLACEHOLDER.match(sentence) or sentence.startswith("["):
        return None
    match = _SPLIT.search(sentence)
    if not match:
        return None
    prefix = sentence[:match.end()].strip()
    completion = sentence[match.end():].strip().rstrip(".!?;: ")
    if len(prefix.split()) < 2 or len(completion.split()) < 2 or len(completion.split()) > 20:
        return None
    return prefix, completion


def _question_prompt(prefix: str, completion: str) -> str | None:
    match = _SPLIT.search(prefix)
    if not match:
        return None
    subject = prefix[:match.start()].strip()
    verb = match.group().casefold()
    if not subject or len(subject.split()) > 9:
        return None
    if verb in {"is", "was", "are", "were"}:
        temporal = bool(re.search(
            r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|noon|midnight|today|tomorrow|\d{1,2}:\d{2}|am|pm)\b",
            completion, re.I,
        ))
        if temporal:
            return f"When {verb} {subject.casefold()}?"
        return f"What {verb} {subject.casefold()}?"
    base = {"uses": "use", "splits": "split", "shows": "show", "includes": "include",
            "contains": "contain", "lists": "list", "combines": "combine", "connects": "connect",
            "decreases": "decrease", "defines": "define", "supports": "support",
            "identifies": "identify", "minimizes": "minimize", "estimates": "estimate",
            "improves": "improve", "measures": "measure", "requires": "require",
            "provides": "provide"}.get(verb, verb)
    auxiliary = "do" if subject.casefold().split()[-1].endswith("s") else "does"
    return f"What {auxiliary} {subject.casefold()} {base}?"


def _study_item(prefix: str, completion: str) -> tuple[str, str] | None:
    """Ask for one atomic relationship instead of an entire statement."""
    match = _SPLIT.search(prefix)
    if not match:
        return None
    verb = match.group().casefold()
    if verb in {"split", "splits"}:
        parts = re.split(r"\s+using\s+", completion, maxsplit=1, flags=re.I)
        if len(parts) == 2 and all(len(part.split()) >= 1 for part in parts):
            subject = re.sub(r"\brecursively\s*$", "", prefix[:match.start()], flags=re.I).strip()
            auxiliary = "do" if subject.casefold().split()[-1].endswith("s") else "does"
            return f"What {auxiliary} {subject.casefold()} use to split {parts[0].casefold()}?", parts[1]
    prompt = _question_prompt(prefix, completion)
    return (prompt, completion) if prompt else None


def build_quiz(chunks: list[DocumentChunk], question_count: int = 5, seed: int = 0) -> Quiz:
    if question_count < 1:
        raise ValueError("question count must be positive")
    rng = random.Random(seed)
    candidates: list[tuple[DocumentChunk, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for chunk in chunks:
        for sentence in _sentences(chunk.text):
            fact = _fact(sentence)
            if fact and (fact[0].casefold(), fact[1].casefold()) not in seen:
                seen.add((fact[0].casefold(), fact[1].casefold()))
                candidates.append((DocumentChunk(
                    chunk.chunk_id, sentence, replace(chunk.source, excerpt=sentence), chunk.modality
                ), *fact))
    if len(candidates) < 2:
        raise ValueError("selected materials need at least two distinct extractable statements for practice questions")
    rng.shuffle(candidates)
    questions: list[QuizQuestion] = []
    for chunk, prefix, completion in candidates:
        item = _study_item(prefix, completion)
        if not item:
            continue
        prompt, correct = item
        if not prompt or _content_words(correct) & _content_words(prompt):
            continue
        alternatives = list(dict.fromkeys(
            other_item[1] for _, other_prefix, ending in candidates
            if (other_item := _study_item(other_prefix, ending))
            and other_item[1].casefold() != correct.casefold()
            and other_prefix.casefold() != prefix.casefold()
            and not _too_similar(correct, other_item[1])
            and not _too_similar(prefix, other_prefix)

        ))[:3]
        if not alternatives:
            continue
        choices = [correct, *alternatives]
        rng.shuffle(choices)
        questions.append(QuizQuestion(
            question_id=f"q{len(questions) + 1}",
            prompt=prompt,
            choices=tuple(choices),
            correct_choice=choices.index(correct),
            source=chunk.source,
        ))
        if len(questions) == question_count:
            break
    if not questions:
        raise ValueError("selected materials do not have enough distinct extractable statements")
    return Quiz(questions=tuple(questions))


def build_generated_quiz(
    chunks: list[DocumentChunk],
    generate: Callable[..., dict[str, Any] | None],
    question_count: int = 5,
    seed: int = 0,
) -> Quiz:
    """Reject malformed/unanchored model items; never invent an answer key."""
    if question_count < 1:
        raise ValueError("question count must be positive")
    rng = random.Random(seed)
    candidates = [chunk for chunk in chunks if chunk.text and not _PLACEHOLDER.fullmatch(chunk.text.strip())]
    corpus_text = " ".join(chunk.text for chunk in chunks).casefold()
    rng.shuffle(candidates)
    questions: list[QuizQuestion] = []
    seen: set[str] = set()
    for chunk in candidates[:max(question_count * 3, 8)]:
        try:
            item = generate(chunk.text, image_path=chunk.source.image_path)
        except (OSError, RuntimeError, ValueError):
            break
        if not isinstance(item, dict):
            continue
        prompt, correct, distractors, explanation = (
            item.get("prompt"), item.get("correct"), item.get("distractors"), item.get("explanation")
        )
        if not all(isinstance(value, str) and value.strip() for value in (prompt, correct, explanation)):
            continue
        if not isinstance(distractors, list) or len(distractors) != 3 or not all(
            isinstance(value, str) and value.strip() for value in distractors
        ):
            continue
        if len(prompt) > 300 or len(correct) > 100 or len(explanation) > 500:
            continue
        supporting_sentences = [sentence for sentence in _sentences(chunk.text)
                                if correct.casefold() in sentence.casefold()]
        subject_terms = _content_words(prompt) - _content_words(correct)
        if (not supporting_sentences or not subject_terms
                or not any(subject_terms & _content_words(sentence) for sentence in supporting_sentences)
                or prompt.casefold() in seen
                or correct.casefold() in prompt.casefold()):
            continue
        if len({choice.casefold().strip() for choice in [correct, *distractors]}) != 4:
            continue
        if any(value.casefold() in corpus_text for value in distractors):
            continue
        seen.add(prompt.casefold())
        choices = [correct, *distractors]
        rng.shuffle(choices)
        excerpt = supporting_sentences[0]
        questions.append(QuizQuestion(
            question_id=f"q{len(questions) + 1}",
            prompt=prompt.strip(),
            choices=tuple(choices),
            correct_choice=choices.index(correct),
            source=replace(chunk.source, excerpt=excerpt),
            explanation=explanation.strip(),
        ))
        if len(questions) >= question_count:
            break
    if not questions:
        raise ValueError("vision model did not produce a verifiable source-grounded practice question")
    return Quiz(tuple(questions))


def score_quiz(quiz: Quiz, answers: Mapping[str, int]) -> dict[str, int]:
    answered = sum(question.question_id in answers for question in quiz.questions)
    score = sum(answers.get(question.question_id) == question.correct_choice for question in quiz.questions)
    return {"score": score, "total": len(quiz.questions), "answered": answered}


def reveal_solution(quiz: Quiz, question_index: int) -> QuizQuestion:
    if question_index < 0 or question_index >= len(quiz.questions):
        raise IndexError("question index out of range")
    return reveal_question(quiz.questions[question_index])


def feedback_quiz(
    quiz: Quiz,
    answers: Mapping[str, int],
    reveal_question_id: str | None = None,
) -> dict[str, object]:
    """Return feedback only for answered questions or one explicitly requested solution."""
    score = score_quiz(quiz, answers)
    feedback = []
    for question in quiz.questions:
        answered = question.question_id in answers
        requested = question.question_id == reveal_question_id
        if not answered and not requested:
            continue
        revealed = reveal_question(question)
        selected = answers.get(question.question_id)
        item = {
            "question_id": question.question_id,
            "answered": answered,
            "correct": answered and selected == question.correct_choice,
            "selected_choice": selected,
            "correct_choice": revealed.correct_choice,
            "choices": list(question.choices),
            "explanation": revealed.explanation,
            "source": revealed.source.as_dict(),
        }
        feedback.append(item)
    return {**score, "feedback": feedback}
