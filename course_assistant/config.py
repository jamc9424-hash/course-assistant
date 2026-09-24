"""Course Assistant configuration.

All endpoints and credentials are read from environment variables / a local
``.env`` file (gitignored). Nothing here is a real secret. Fields default to
``None`` and are resolved in ``__post_init__`` (env -> hard-coded class default),
so explicitly-passed values always win and env/.env are honoured even when read
is delayed until after the module is imported.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _load_dotenv(path: Path) -> None:
    """Minimal .env parser: KEY=VALUE lines, ignores blank/#, strips quotes."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val is not None and val != "" else default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    """Runtime configuration for the course assistant."""

    api_key: Optional[str] = None

    # Endpoints (default to the class services; override via env/.env).
    vision_llm_url: Optional[str] = None
    text_embedding_url: Optional[str] = None
    visual_embedding_url: Optional[str] = None
    rerank_url: Optional[str] = None
    document_parser_url: Optional[str] = None

    # Model names (match the services' /v1/models).
    vision_model: Optional[str] = None
    text_embed_model: Optional[str] = None
    visual_embed_model: Optional[str] = None
    rerank_model: Optional[str] = None
    parser_model: Optional[str] = None

    # Retrieval tuning.
    text_top_k: Optional[int] = None
    visual_top_k: Optional[int] = None
    keyword_top_k: Optional[int] = None
    rerank_top_n: Optional[int] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    rrf_k: Optional[int] = None

    # Routing toggles (set false to disable a retriever gracefully).
    use_keyword: Optional[bool] = None
    use_text_vector: Optional[bool] = None
    use_visual_vector: Optional[bool] = None
    use_rerank: Optional[bool] = None

    # HTTP resilience.
    request_timeout: Optional[float] = None
    max_attempts: Optional[int] = None
    backoff_base: Optional[float] = None

    # Local storage (gitignored).
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("COURSE_ASSISTANT_DATA", "data")).resolve()
    )

    def __post_init__(self) -> None:
        self.api_key = self.api_key or _env("CLASS_SERVICE_API_KEY", "")
        self.vision_llm_url = self.vision_llm_url or _env("VISION_LLM_URL", "http://dobolyi.com:9001")
        self.text_embedding_url = self.text_embedding_url or _env("TEXT_EMBEDDING_URL", "http://dobolyi.com:9002")
        self.visual_embedding_url = self.visual_embedding_url or _env("VISUAL_EMBEDDING_URL", "http://dobolyi.com:9003")
        self.rerank_url = self.rerank_url or _env("RERANKING_URL", "http://dobolyi.com:9004")
        self.document_parser_url = self.document_parser_url or _env("DOCUMENT_PARSER_URL", "http://dobolyi.com:9005")
        self.vision_model = self.vision_model or _env("VISION_MODEL", "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit")
        self.text_embed_model = self.text_embed_model or _env("TEXT_EMBED_MODEL", "nvidia/Nemotron-3-Embed-1B-BF16")
        self.visual_embed_model = self.visual_embed_model or _env("VISUAL_EMBED_MODEL", "Qwen/Qwen3-VL-Embedding-2B")
        self.rerank_model = self.rerank_model or _env("RERANK_MODEL", "Qwen/Qwen3-VL-Reranker-2B")
        self.parser_model = self.parser_model or _env("PARSER_MODEL", "dots.mocr")
        self.text_top_k = self.text_top_k if self.text_top_k is not None else _env_int("TEXT_TOP_K", 6)
        self.visual_top_k = self.visual_top_k if self.visual_top_k is not None else _env_int("VISUAL_TOP_K", 4)
        self.keyword_top_k = self.keyword_top_k if self.keyword_top_k is not None else _env_int("KEYWORD_TOP_K", 6)
        self.rerank_top_n = self.rerank_top_n if self.rerank_top_n is not None else _env_int("RERANK_TOP_N", 6)
        self.chunk_size = self.chunk_size if self.chunk_size is not None else _env_int("CHUNK_SIZE", 600)
        self.chunk_overlap = self.chunk_overlap if self.chunk_overlap is not None else _env_int("CHUNK_OVERLAP", 120)
        self.rrf_k = self.rrf_k if self.rrf_k is not None else _env_int("RRF_K", 60)
        self.use_keyword = _env("USE_KEYWORD", "1") == "1" if self.use_keyword is None else self.use_keyword
        self.use_text_vector = _env("USE_TEXT_VECTOR", "1") == "1" if self.use_text_vector is None else self.use_text_vector
        self.use_visual_vector = _env("USE_VISUAL_VECTOR", "1") == "1" if self.use_visual_vector is None else self.use_visual_vector
        self.use_rerank = _env("USE_RERANK", "1") == "1" if self.use_rerank is None else self.use_rerank
        self.request_timeout = self.request_timeout if self.request_timeout is not None else float(_env("REQUEST_TIMEOUT", "240"))
        self.max_attempts = self.max_attempts if self.max_attempts is not None else _env_int("MAX_ATTEMPTS", 5)
        self.backoff_base = self.backoff_base if self.backoff_base is not None else float(_env("BACKOFF_BASE", "1.5"))
        self.data_dir = Path(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)


def load_settings(env_file: Optional[Path | str] = None) -> Settings:
    """Build settings from environment plus an optional gitignored .env file."""
    path = Path(env_file) if env_file else Path(__file__).resolve().parent.parent / ".env"
    _load_dotenv(Path(path))
    return Settings()
