"""Request and response formats confirmed against the live class services (ports 9001-9005).

These tests use a fake HTTP opener, so they run offline. They exist because the adapters
previously passed unit tests while failing against the real servers.
"""

import json

import pytest

from course_assistant import services
from course_assistant.services import ClassServiceClient, ServiceReranker, ServiceSettings


class _Reply:
    def __init__(self, body):
        self._body = json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _client(handler, **env):
    calls = []

    def opener(request, timeout):
        payload = json.loads(request.data.decode())
        calls.append((request.full_url, payload))
        return _Reply(handler(request.full_url, payload))

    settings = ServiceSettings.from_env({"CLASS_SERVICE_API_KEY": "dummy", "CLASS_SERVICE_ALLOW_INSECURE_HTTP": "true", **env})
    return ClassServiceClient(settings, opener=opener), calls


@pytest.fixture(autouse=True)
def _clear_caches():
    services._EMBEDDING_CACHE.clear()
    services._PARSE_CACHE.clear()
    yield
    services._EMBEDDING_CACHE.clear()
    services._PARSE_CACHE.clear()


def test_text_embeddings_read_the_nested_float_list_returned_by_port_9002():
    client, calls = _client(lambda url, payload: {"embeddings": {"float": [[0.1, 0.2], [0.3, 0.4]]}, "texts": payload["texts"]})
    assert client.embed_text(["passage: a", "passage: b"]) == [[0.1, 0.2], [0.3, 0.4]]
    assert calls[0][1]["texts"] == ["passage: a", "passage: b"] and "input" not in calls[0][1]


def test_text_embeddings_are_batched_and_cached():
    client, calls = _client(lambda url, payload: {"embeddings": {"float": [[float(len(t))] for t in payload["texts"]]}})
    texts = [f"passage: {'x' * i}" for i in range(70)]
    first = client.embed_text(texts)
    assert len(first) == 70 and [len(c[1]["texts"]) for c in calls] == [32, 32, 6]
    assert client.embed_text(texts) == first and len(calls) == 3  # second build costs no requests


def test_unexpected_text_embedding_reply_is_a_runtime_error_so_the_app_falls_back():
    client, _ = _client(lambda url, payload: {"embeddings": "nope"})
    with pytest.raises(RuntimeError):
        client.embed_text(["x"])
    client, _ = _client(lambda url, payload: {"embeddings": {"float": [[0.1]]}})
    with pytest.raises(RuntimeError):
        client.embed_text(["x", "y"])


def test_visual_embeddings_send_one_image_per_request_as_a_chat_message():
    def handler(url, payload):
        return {"data": [{"embedding": [1.0 if "messages" in payload else 2.0]}]}

    client, calls = _client(handler)
    vectors = client.embed_visual([{"text": "slide one", "image": "data:image/png;base64,AAAA"}, {"text": "slide two", "image": "data:image/png;base64,BBBB"}])
    assert vectors == [[1.0], [1.0]] and len(calls) == 2
    for _, payload in calls:
        content = payload["messages"][0]["content"]
        assert content[0]["type"] == "image_url" and content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert content[1]["type"] == "text" and "input" not in payload
    # A text query is sent as a plain string input.
    assert client.embed_visual([{"text": "find the meme"}]) == [[2.0]]
    assert calls[-1][1]["input"] == "find the meme" and "messages" not in calls[-1][1]
    # Identical slides are not embedded twice.
    client.embed_visual([{"text": "slide one", "image": "data:image/png;base64,AAAA"}])
    assert len(calls) == 3


def test_reranker_converts_documents_and_returns_scores_in_input_order(tmp_path):
    image = tmp_path / "slide.png"
    image.write_bytes(b"png-bytes")

    def handler(url, payload):
        # The service may return results sorted by relevance, each carrying its document index.
        return {"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]}

    client, calls = _client(handler)

    class Source:
        def __init__(self, image_path):
            self.image_path = image_path

    class Chunk:
        def __init__(self, text, image_path=None):
            self.text, self.source = text, Source(image_path)

    scores = ServiceReranker(client).score_many("vibe coding", [Chunk("plain text"), Chunk("slide text", str(image))])
    assert scores == [0.2, 0.9]
    documents = calls[0][1]["documents"]
    assert documents[0] == "plain text"
    assert documents[1]["content"][0]["type"] == "image_url" and documents[1]["content"][1] == {"type": "text", "text": "slide text"}
    assert "image" not in documents[1] and "text" not in documents[1]


def test_reranker_rejects_out_of_range_indexes():
    client, _ = _client(lambda url, payload: {"results": [{"index": 5, "relevance_score": 0.9}]})
    with pytest.raises(RuntimeError):
        client.rerank("q", ["a"])


def test_chat_requests_turn_thinking_off_at_the_top_level():
    client, calls = _client(lambda url, payload: {"choices": [{"message": {"content": "Answer [1]."}}]})
    assert client.generate_answer("q", [{"document": "d", "location": "slide 1", "excerpt": "e"}]) == "Answer [1]."
    client.generate_quiz_item("Some source text about retrieval.")
    for _, payload in calls:
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
        assert "extra_body" not in payload


def test_visual_parses_are_cached_per_image_and_instruction():
    client, calls = _client(lambda url, payload: {"choices": [{"message": {"content": "text on slide"}}]})
    first = client.parse_image("data:image/png;base64,AAAA", "describe")
    assert client.parse_image("data:image/png;base64,AAAA", "describe") is first and len(calls) == 1
    client.parse_image("data:image/png;base64,BBBB", "describe")
    assert len(calls) == 2


def test_slide_descriptions_come_from_the_vision_model_and_are_cached():
    client, calls = _client(lambda url, payload: {"choices": [{"message": {"content": "A meme with a caption."}}]},
                            VISION_LLM_ENDPOINT="http://example.test/v1/chat/completions", VISION_LLM_MODEL="vision-model")
    assert client.describe_image("data:image/png;base64,AAAA", "Describe the slide.") == "A meme with a caption."
    assert client.describe_image("data:image/png;base64,AAAA", "Describe the slide.") == "A meme with a caption."
    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "http://example.test/v1/chat/completions" and payload["model"] == "vision-model"
    assert payload["messages"][0]["content"][0]["type"] == "image_url"
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_assistant_prefers_vision_description_and_falls_back_to_the_parser(tmp_path):
    from course_assistant.assistant import CourseAssistant
    from course_assistant.models import SourceEvidence

    image = tmp_path / "slide.png"
    image.write_bytes(b"png")
    source = SourceEvidence(document="deck.pptx", page_or_slide="slide 3", excerpt="Vibe Coding", image_path=str(image))

    class Both:
        def describe_image(self, image_data_url, instruction):
            return "Vision model description."

        def parse_image(self, image_data_url, instruction):
            raise AssertionError("parser should not be called when the vision model answers")

    class VisionDown:
        def describe_image(self, image_data_url, instruction):
            raise RuntimeError("vision model unavailable")

        def parse_image(self, image_data_url, instruction):
            return {"choices": [{"message": {"content": "Parser text."}}]}

    assert CourseAssistant([], None, Both())._describe_visual(source) == "Vision model description."
    assert CourseAssistant([], None, VisionDown())._describe_visual(source) == "Parser text."


def test_model_refusal_is_honored_even_when_keywords_overlap():
    """The schedule mentions "Quiz 1", but nothing states a class average. When the answer model
    says it cannot find the information, the app must say so and cite nothing."""
    from course_assistant.assistant import CourseAssistant
    from course_assistant.ingest import ingest_text

    class RefusingModel:
        def embed_text(self, texts):
            raise RuntimeError("embeddings not needed for this test")

        def generate_answer(self, question, evidence):
            return "I could not find that information in the selected course materials."

    chunk = ingest_text("Week 6 schedule: Quiz 1 and Assignment 1 review in class, followed by a hands-on lab.", "syllabus.txt")[0]
    response = CourseAssistant.from_chunks([chunk], service_client=RefusingModel()).ask("What was the class average on Quiz 1?")
    assert response.answer == "I could not find that information in the selected course materials."
    assert not response.sources

    class AnsweringModel:
        def embed_text(self, texts):
            raise RuntimeError("embeddings not needed for this test")

        def generate_answer(self, question, evidence):
            return "Quiz 1 and Assignment 1 review in class [1]."

    answered = CourseAssistant.from_chunks([chunk], service_client=AnsweringModel()).ask("When is Quiz 1 and the Assignment 1 review?")
    assert answered.sources and "Quiz 1" in answered.answer
