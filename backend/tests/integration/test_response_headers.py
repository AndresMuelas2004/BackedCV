"""Every response carries the safety headers and a cache rule."""

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backedcv.api.headers import cache_rule
from backedcv.main import create_app
from tests.fakes import FakeLLM


def test_an_api_answer_is_never_stored_and_carries_the_safety_headers():
    with TestClient(create_app(llm=FakeLLM(), checkpointer=InMemorySaver())) as client:
        response = client.get("/api/health")

    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_the_documentation_pages_keep_their_cdn_scripts():
    with TestClient(create_app(llm=FakeLLM(), checkpointer=InMemorySaver())) as client:
        response = client.get("/docs")

    assert response.status_code == 200
    assert "content-security-policy" not in response.headers


def test_cache_rules_by_path():
    assert cache_rule("/assets/index-abc123.js") == "public, max-age=31536000, immutable"
    assert cache_rule("/fonts/public-sans.woff2") == "public, max-age=2592000"
    assert cache_rule("/") == "no-cache"
    assert cache_rule("/api/analyses/123") == "no-store"
