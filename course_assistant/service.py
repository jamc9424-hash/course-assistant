"""Thin, resilient HTTP clients for the five class services.

Service failures are surfaced as :class:`ServiceError` so the app can degrade
gracefully (the assignment requires handling unavailable model services).
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Iterable, Optional

import requests

from .config import Settings


class ServiceError(RuntimeError):
    """Raised when a class service is unreachable or returns an error."""

    def __init__(self, service: str, message: str):
        self.service = service
        self.message = message
        super().__init__(f"[{service}] {message}")


class _Client:
    def __init__(self, settings: Settings):
        self.s = settings
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {settings.api_key}",
                "Accept": "application/json",
            }
        )

    def _post(self, service: str, url: str, payload: dict[str, Any],
              timeout: Optional[float] = None) -> dict[str, Any]:
        """POST with patient retries (some servers return empty-bodied 200s)."""
        timeout = timeout or self.s.request_timeout
        last: Optional[Exception] = None
        for attempt in range(self.s.max_attempts):
            try:
                resp = self.session.post(url, json=payload, timeout=timeout)
                if resp.status_code == 204 or not resp.content:
                    # empty body 200: retry per recommendation
                    if attempt + 1 >= self.s.max_attempts:
                        raise ServiceError(
                            service, f"server returned empty body after retries (HTTP {resp.status_code})"
                        )
                    time.sleep(self.s.backoff_base ** (attempt + 1))
                    continue
                if resp.status_code >= 400:
                    raise ServiceError(
                        service,
                        f"HTTP {resp.status_code}: {resp.text[:300]}",
                    )
                return resp.json()
            except requests.RequestException as e:
                last = e
                if attempt + 1 < self.s.max_attempts:
                    time.sleep(self.s.backoff_base ** (attempt + 1))
        raise ServiceError(service, f"connection failed: {last}")

    def _encode_image_data(self, image_path: str) -> str:
        mime = "image/png"
        if image_path.lower().endswith(".jpg") or image_path.lower().endswith(".jpeg"):
            mime = "image/jpeg"
        b64 = base64.b64encode(open(image_path, "rb").read()).decode("utf-8")
        return f"data:{mime};base64,{b64}"


class VisionLLMClient(_Client):
    """Port 9001: vision-capable chat LLM."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = 700,
        temperature: float = 0.0,
        thinking_budget: int = 0,          # 0 keeps content deterministic
    ) -> str:
        body = self._post(
            "vision-llm",
            f"{self.s.vision_llm_url}/v1/chat/completions",
            {
                "model": self.s.vision_model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "thinking_token_budget": thinking_budget,
            },
        )
        msg = body["choices"][0]["message"]
        content = msg.get("content")
        if not content:
            # reasoning model may return content in `reasoning`; surface it.
            content = msg.get("reasoning") or ""
        return content

    def summarize_image(self, image_path: str, prompt: str) -> str:
        url = self._encode_image_data(image_path)
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ]
        return self.chat(msgs, max_tokens=500)


class TextEmbeddingClient(_Client):
    """Port 9002: text embeddings (OpenAI-compatible /v1/embeddings)."""

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        texts = list(texts)
        if not texts:
            return []
        body = self._post(
            "text-embedding",
            f"{self.s.text_embedding_url}/v1/embeddings",
            {"model": self.s.text_embed_model, "input": texts},
            timeout=min(self.s.request_timeout, 120),
        )
        data = sorted(body["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def dim(self) -> int:
        try:
            vec = self.embed(["probe"])[0]
            return len(vec)
        except ServiceError:
            return 0


class VisualEmbeddingClient(_Client):
    """Port 9003: visual embeddings (chat-variant accepts images + text)."""

    def _embed_messages(self, content: list[dict[str, Any]]) -> list[float]:
        body = self._post(
            "visual-embedding",
            f"{self.s.visual_embedding_url}/v1/embeddings",
            {
                "model": self.s.visual_embed_model,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=min(self.s.request_timeout, 180),
        )
        return body["data"][0]["embedding"]

    def embed_image(self, image_path: str, text: str = "") -> list[float]:
        url = self._encode_image_data(image_path)
        content: list[dict[str, Any]] = [{"type": "image_url", "image_url": {"url": url}}]
        if text:
            content.append({"type": "text", "text": text})
        return self._embed_messages(content)

    def embed_text(self, text: str) -> list[float]:
        return self._embed_messages([{"type": "text", "text": text}])


class RerankClient(_Client):
    """Port 9004: multimodal reranker (Cohere-style /v1/rerank)."""

    def rerank(
        self,
        query: str,
        documents: list,                      # each str OR {"content":[...]}
        top_n: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        if not documents:
            return []
        top_n = top_n or len(documents)
        body = self._post(
            "rerank",
            f"{self.s.rerank_url}/v1/rerank",
            {
                "model": self.s.rerank_model,
                "query": query,               # plain string (Cohere-style)
                "documents": documents,
                "top_n": top_n,
            },
            timeout=min(self.s.request_timeout, 180),
        )
        return body["results"]

    def score(self, query: str, documents: list[str]) -> list[float]:
        # Cohere /v1/rerank accepts plain-string documents; keep that shape.
        docs = [{"content": [{"type": "text", "text": d}]} for d in documents]
        results = self.rerank(query, docs)
        scored = [0.0] * len(documents)
        for r in results:
            idx = int(r["index"])
            if 0 <= idx < len(documents):
                scored[idx] = r["relevance_score"]
        return scored


class DocumentParserClient(_Client):
    """Port 9005: OCR / markdown extraction from an image."""

    def parse_image(self, image_path: str, mime: str = "image/png") -> str:
        url = self._encode_image_data(image_path)
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Extract all visible text from this page/slide "
                            "verbatim. Return plain text only, preserving "
                            "reading order."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ]
        body = self._post(
            "document-parser",
            f"{self.s.document_parser_url}/v1/chat/completions",
            {"model": self.s.parser_model, "messages": messages, "temperature": 0.0},
            timeout=min(self.s.request_timeout, 180),
        )
        msg = body["choices"][0]["message"]
        content = msg.get("content") or msg.get("reasoning") or ""
        return content.strip()
