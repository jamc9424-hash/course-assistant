from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping




def image_path_to_data_url(path: str) -> str:
    image_path = Path(path)
    if not image_path.is_file():
        raise FileNotFoundError(path)
    media_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


@dataclass(frozen=True)
class ServiceSettings:
    api_key: str
    vision_endpoint: str
    vision_model: str
    text_embedding_endpoint: str
    text_embedding_model: str
    visual_embedding_endpoint: str
    visual_embedding_model: str
    reranker_endpoint: str
    reranker_model: str
    parser_endpoint: str
    parser_model: str
    allow_insecure_http: bool

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ServiceSettings":
        values = dict(os.environ if env is None else env)
        return cls(
            api_key=values.get("CLASS_SERVICE_API_KEY", ""),
            vision_endpoint=values.get("VISION_LLM_ENDPOINT", "http://dobolyi.com:9001/v1/chat/completions"),
            vision_model=values.get("VISION_LLM_MODEL", "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit"),
            text_embedding_endpoint=values.get("TEXT_EMBEDDING_ENDPOINT", "http://dobolyi.com:9002/v2/embed"),
            text_embedding_model=values.get("TEXT_EMBEDDING_MODEL", "nvidia/Nemotron-3-Embed-1B-BF16"),
            visual_embedding_endpoint=values.get("VISUAL_EMBEDDING_ENDPOINT", "http://dobolyi.com:9003/v1/embeddings"),
            visual_embedding_model=values.get("VISUAL_EMBEDDING_MODEL", "Qwen/Qwen3-VL-Embedding-2B"),
            reranker_endpoint=values.get("RERANKER_ENDPOINT", "http://dobolyi.com:9004/rerank"),
            reranker_model=values.get("RERANKER_MODEL", "Qwen/Qwen3-VL-Reranker-2B"),
            parser_endpoint=values.get("DOCUMENT_PARSER_ENDPOINT", "http://dobolyi.com:9005/v1/chat/completions"),
            parser_model=values.get("DOCUMENT_PARSER_MODEL", "dots.mocr"),
            allow_insecure_http=values.get("CLASS_SERVICE_ALLOW_INSECURE_HTTP", "false").casefold() == "true",
        )


class ServiceReranker:
    def __init__(self, client: "ClassServiceClient"):
        self.client = client

    def score(self, query: str, chunk: Any) -> float:
        scores = self.client.rerank(query, [{"text": chunk.text, "image": chunk.source.image_path}])
        return float(scores[0]) if scores else 0.0


class ClassServiceClient:
    def __init__(self, settings: ServiceSettings, opener: Callable[..., Any] | None = None, timeout: float = 60.0):
        self.settings = settings
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout

    def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if urllib.parse.urlparse(endpoint).scheme == "http" and not self.settings.allow_insecure_http:
            raise RuntimeError("class service endpoint uses HTTP; enable it only on a trusted class network or use HTTPS")
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"class service request failed for {endpoint}") from exc

    def generate_answer(self, question: str, evidence: list[dict[str, Any]]) -> str:
        """Generate a grounded answer with the class vision-capable LLM."""
        evidence_blocks: list[str] = []
        content: list[dict[str, Any]] = []
        for index, item in enumerate(evidence, start=1):
            location = item.get("location", "unknown location")
            excerpt = item.get("excerpt", "")
            evidence_blocks.append(f"[{index}] {item.get('document', 'document')} — {location}: {excerpt}")
            image_path = item.get("image_path")
            if image_path:
                try:
                    content.append({"type": "image_url", "image_url": {"url": image_path_to_data_url(image_path)}})
                except FileNotFoundError:
                    pass
        prompt = (
            "Answer the student's question using only the supplied course evidence. "
            "Explain uncertainty when the evidence is insufficient. Do not invent facts, "
            "citations, page numbers, or visual details. Cite evidence inline as [1], [2].\n\n"
            f"Question: {question}\n\nEvidence:\n" + "\n".join(evidence_blocks)
        )
        content.append({"type": "text", "text": prompt})
        response = self._post(
            self.settings.vision_endpoint,
            {
                "model": self.settings.vision_model,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.2,
                "max_tokens": 512,
                "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
            },
        )
        choices = response.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        answer = message.get("content", "")
        if isinstance(answer, list):
            answer = " ".join(part.get("text", "") for part in answer if isinstance(part, dict))
        return str(answer).strip()

    def embed_text(self, texts: list[str]) -> list[list[float]]:
        response = self._post(
            self.settings.text_embedding_endpoint,
            {"model": self.settings.text_embedding_model, "texts": texts},
        )
        return [item["embedding"] for item in response.get("data", response.get("embeddings", []))]

    def embed_visual(self, inputs: list[Any]) -> list[list[float]]:
        response = self._post(
            self.settings.visual_embedding_endpoint,
            {"model": self.settings.visual_embedding_model, "input": inputs},
        )
        return [item["embedding"] for item in response.get("data", [])]

    def rerank(self, query: str, documents: list[Any]) -> list[float]:
        response = self._post(
            self.settings.reranker_endpoint,
            {"model": self.settings.reranker_model, "query": query, "documents": documents},
        )
        return [item.get("relevance_score", item.get("score", 0.0)) for item in response.get("results", response.get("data", []))]

    def parse_image(self, image_data_url: str, instruction: str) -> dict[str, Any]:
        return self._post(
            self.settings.parser_endpoint,
            {
                "model": self.settings.parser_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_data_url}},
                            {"type": "text", "text": instruction},
                        ],
                    }
                ],
            },
        )
