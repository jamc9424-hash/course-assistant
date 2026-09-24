"""Shared fixtures and service-availability gating for the test suite."""
import socket

import pytest

from course_assistant import config


def _service_reachable(url: str, port: int, key: str) -> bool:
    if not key:
        return False
    host = url.split("://")[-1].split(":")[0]
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except OSError:
        return False


def services_available() -> bool:
    """True only if the class services are reachable and a key is set."""
    s = config.load_settings()
    if not s.api_key:
        return False
    hosts = {url.split("://")[-1].split(":")[0] for url in (
        s.vision_llm_url, s.text_embedding_url, s.visual_embedding_url, s.rerank_url,
        s.document_parser_url)}
    for host in hosts:
        try:
            socket.create_connection((host, 9001), timeout=3).close()
        except OSError:
            return False
    return True


requires_services = pytest.mark.skipif(
    not services_available(),
    reason="class services unavailable or CLASS_SERVICE_API_KEY not set",
)


@pytest.fixture(scope="session")
def live_settings() -> config.Settings:
    """Settings for tests that need the real class services."""
    return config.load_settings()  # reads .env (gitignored) + environment


@pytest.fixture(scope="session")
def services_available_fixture(live_settings) -> bool:
    return services_available()
