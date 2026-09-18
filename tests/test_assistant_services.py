import os

from course_assistant.assistant import CourseAssistant
from course_assistant.ingest import ingest_text
from course_assistant.services import ClassServiceClient, ServiceSettings


def test_assistant_acknowledges_missing_information_without_sources():
    assistant = CourseAssistant.from_chunks(
        [ingest_text("Office hours are Tuesday at noon.", "syllabus.txt")[0]]
    )

    response = assistant.ask("What is the exam weighting?")

    assert response.sources == ()
    assert "could not find" in response.answer.casefold()


def test_assistant_topic_filter_limits_answer_evidence():
    chunks = [
        ingest_text("Decision trees split data using features.", "slides.txt", section="Trees")[0],
        ingest_text("Office hours are Tuesday at noon.", "syllabus.txt", section="Policies")[0],
    ]
    assistant = CourseAssistant.from_chunks(chunks)

    response = assistant.ask("When are office hours?", topic="Trees")

    assert response.sources == ()
    assert "could not find" in response.answer.casefold()


def test_service_client_uses_server_side_key_and_texts_contract(monkeypatch):
    calls = []

    class Response:
        def read(self):
            return b'{"data":[{"embedding":[0.1,0.2]}]}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return Response()

    monkeypatch.setattr("course_assistant.services.urllib.request.urlopen", fake_urlopen)
    settings = ServiceSettings.from_env(
        {
            "CLASS_SERVICE_API_KEY": "test-only",
            "TEXT_EMBEDDING_ENDPOINT": "http://example.test/embed",
            "TEXT_EMBEDDING_MODEL": "text-model",
        }
    )
    result = ClassServiceClient(settings, opener=fake_urlopen).embed_text(["hello"])

    assert result == [[0.1, 0.2]]
    request, _ = calls[0]
    assert request.headers["Authorization"] == "Bearer test-only"
    assert '"texts": ["hello"]' in request.data.decode()
    assert "test-only" not in repr(result)
