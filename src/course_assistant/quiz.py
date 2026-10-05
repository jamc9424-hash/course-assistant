from __future__ import annotations

import random
import re
from dataclasses import replace
from typing import Mapping

from .models import DocumentChunk, Quiz, QuizQuestion, reveal_question


_FOCUS_STOPWORDS = {"a", "an", "the", "is", "are", "was", "were", "using", "with", "from", "this", "that", "and", "of", "to", "in"}


def _focus_phrase(sentence: str) -> str:
    words = [
        word.casefold()
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*", sentence)
        if word.casefold() not in _FOCUS_STOPWORDS
    ]
    return " ".join(words[:5]) or "the selected material"


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if len(part.strip()) >= 20]


def _question_prompt(statement: str) -> str:
    """Turn an evidence sentence into a focused study question."""
    words = statement.strip().rstrip(".").split()
    subject_words: list[str] = []
    for word in words:
        cleaned = re.sub(r"[^A-Za-z0-9'-]", "", word)
        if cleaned.casefold() in {"a", "an", "the"} and not subject_words:
            continue
        if cleaned.casefold() in {
            "is", "are", "was", "were", "uses", "use", "shows", "show", "includes", "contains", "lists",
            "split", "splits", "combine", "combines", "connects", "connect", "decrease", "decreases",
            "decreasing", "defines", "define", "supports", "support", "identifies", "identify", "remain",
        }:
            break
        if cleaned:
            subject_words.append(cleaned)
        if len(subject_words) >= 6:
            break
    subject = " ".join(subject_words).strip()
    if subject:
        return f"Which statement best describes {subject.casefold()}?"
    return "Which statement is directly supported by the selected course material?"


def build_quiz(chunks: list[DocumentChunk], question_count: int = 5, seed: int = 0) -> Quiz:
    rng = random.Random(seed)
    candidates = []
    seen_statements = set()
    for chunk in chunks:
        for sentence in _sentences(chunk.text):
            key = sentence.casefold()
            if key not in seen_statements:
                seen_statements.add(key)
                candidates.append((chunk, sentence))
    if len(candidates) < 2:
        raise ValueError("selected materials need at least two distinct supported statements for a multiple-choice quiz")
    rng.shuffle(candidates)
    questions: list[QuizQuestion] = []
    for index, (chunk, correct) in enumerate(candidates[:question_count]):
        distractors = [
            sentence for other, sentence in candidates
            if sentence != correct and _focus_phrase(sentence) != _focus_phrase(correct)
        ]
        distractors = distractors[:3]
        choices = [correct, *distractors]
        rng.shuffle(choices)
        questions.append(
            QuizQuestion(
                question_id=f"q{index + 1}",
                prompt=_question_prompt(correct),
                choices=tuple(choices),
                correct_choice=choices.index(correct),
                source=chunk.source,
            )
        )
    return Quiz(questions=tuple(questions))


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
            "explanation": revealed.explanation,
            "source": revealed.source.as_dict(),
        }
        feedback.append(item)
    return {**score, "feedback": feedback}
