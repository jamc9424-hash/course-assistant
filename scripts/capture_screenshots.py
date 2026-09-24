"""Capture the app screenshots used in README.md.

Loads the running Course Assistant (http://127.0.0.1:7580) in headless
Chromium, drives the two demo workflows, and saves PNGs to docs/screenshots/.

  * answer_with_slide_image.png  — grounded answer + supporting slide image
  * quiz_feedback.png            — a checked quiz question with explanation/source

Requires: ``pip install playwright && python -m playwright install chromium``.
Run the app first: ``python -m course_assistant.app``.
"""
from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

APP_URL = "http://127.0.0.1:7580"
QUESTIONS = {
    "Ask a question": "Find the slide with the Vibe Coding on Prod meme and "
                     "describe what the image and text show.",
}
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"


def _click_tab(page, name: str) -> None:
    page.get_by_role("tab", name=name).first.click()
    page.wait_for_timeout(1200)


def _fill_question(page, text: str) -> None:
    tb = page.locator("textarea").first
    tb.fill(text)
    page.wait_for_timeout(300)


def capture_answer(page) -> None:
    _click_tab(page, "Ask a question")
    _fill_question(page, QUESTIONS["Ask a question"])
    page.get_by_role("button", name="Ask").first.click()
    # wait for the rendered "Answer" heading, then let the slide image load
    page.get_by_role("heading", name="Answer").wait_for(timeout=120_000)
    page.wait_for_timeout(4000)
    page.screenshot(path=str(OUT / "answer_with_slide_image.png"),
                    full_page=True)
    print("saved answer_with_slide_image.png")


def capture_quiz(page) -> None:
    _click_tab(page, "Practice quiz")
    page.get_by_role("button", name="Generate quiz").first.click()
    page.get_by_role("button", name="Check my answers").wait_for(timeout=120_000)
    page.wait_for_timeout(5000)
    # pick the first option of the first visible radio
    radios = page.locator("input[type=radio]:visible")
    if radios.count() == 0:
        # fallback: gradio renders radios as labelled buttons
        first_opt = page.locator("label:visible").first
        first_opt.click()
    else:
        radios.first.check(force=True)
    page.wait_for_timeout(600)
    page.get_by_role("button", name="Check my answers").first.click()
    page.get_by_text("Score:", exact=False).first.wait_for(timeout=30_000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT / "quiz_feedback.png"), full_page=True)
    print("saved quiz_feedback.png")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2000)
        capture_answer(page)
        capture_quiz(page)
        browser.close()
    print("done ->", OUT)


if __name__ == "__main__":
    main()
