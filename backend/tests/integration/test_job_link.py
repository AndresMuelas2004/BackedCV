import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backedcv.main import create_app
from backedcv.settings import get_settings
from tests.fakes import FakeLLM

GUEST_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4431992044"
VIEW_URL = "https://www.linkedin.com/jobs/view/4431992044/"
VALID_LINK = (
    "https://www.linkedin.com/jobs/view/junior-data-analyst-at-example-corp-4431992044/?refId=abc"
)

PAGE = """
<h2 class="top-card-layout__title topcard__title">Junior Data Analyst</h2>
<a class="topcard__org-name-link topcard__flavor--black-link" href="#">Example Corp</a>
<span class="topcard__flavor topcard__flavor--bullet">Springfield, IL</span>
<div class="description__text"><div class="show-more-less-html__markup">
<p>We need SQL and Python.</p><ul><li>2+ years of SQL</li></ul>
</div></div>
<h3 class="description__job-criteria-subheader">Seniority level</h3>
<span class="description__job-criteria-text">Entry level</span>
"""


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _transport(guest_status=200, view_status=200):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "/jobs-guest/" in str(request.url):
            return httpx.Response(guest_status, text=PAGE)
        return httpx.Response(view_status, text=PAGE)

    return httpx.MockTransport(handler), seen


def _client(transport):
    return TestClient(
        create_app(llm=FakeLLM(), checkpointer=InMemorySaver(), job_link_transport=transport)
    )


def test_success_returns_parsed_posting_from_guest_endpoint():
    transport, seen = _transport()
    with _client(transport) as client:
        response = client.post("/api/job-link", json={"url": VALID_LINK})

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "4431992044"
    assert body["url"] == VIEW_URL
    assert body["title"] == "Junior Data Analyst"
    assert body["company"] == "Example Corp"
    assert body["location"] == "Springfield, IL"
    assert body["closed"] is False
    assert "We need SQL and Python." in body["text"]
    assert "- 2+ years of SQL" in body["text"]
    assert len(seen) == 1
    assert str(seen[0].url) == GUEST_URL
    assert "cookie" not in seen[0].headers


def test_falls_back_to_view_page_when_guest_is_rate_limited():
    transport, seen = _transport(guest_status=429, view_status=200)
    with _client(transport) as client:
        response = client.post("/api/job-link", json={"url": VALID_LINK})

    assert response.status_code == 200
    assert response.json()["job_id"] == "4431992044"
    assert len(seen) == 2


def test_invalid_link_is_rejected_without_any_request(monkeypatch):
    monkeypatch.setenv("BACKEDCV_JOB_LINK_PER_HOUR", "1")
    get_settings.cache_clear()
    transport, seen = _transport()
    with _client(transport) as client:
        invalid = client.post(
            "/api/job-link", json={"url": "https://example.com/jobs/view/4431992044"}
        )
        valid = client.post("/api/job-link", json={"url": VALID_LINK})

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "job_link_invalid"
    # Invalid links use no quota, so the valid call after them still succeeds.
    assert valid.status_code == 200
    assert len(seen) == 1


def test_hourly_limit_blocks_second_call(monkeypatch):
    monkeypatch.setenv("BACKEDCV_JOB_LINK_PER_HOUR", "1")
    get_settings.cache_clear()
    transport, _ = _transport()
    with _client(transport) as client:
        first = client.post("/api/job-link", json={"url": VALID_LINK})
        second = client.post("/api/job-link", json={"url": VALID_LINK})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "job_link_rate_limited"


def test_job_link_limiter_is_separate_from_model_run_limiter(monkeypatch):
    monkeypatch.setenv("BACKEDCV_RATE_LIMIT_PER_HOUR", "1")
    monkeypatch.setenv("BACKEDCV_JOB_LINK_PER_HOUR", "5")
    get_settings.cache_clear()
    transport, _ = _transport()
    with _client(transport) as client:
        first = client.post("/api/job-link", json={"url": VALID_LINK})
        second = client.post("/api/job-link", json={"url": VALID_LINK})

    assert first.status_code == 200
    assert second.status_code == 200


def test_daily_limit_blocks_second_call(monkeypatch):
    monkeypatch.setenv("BACKEDCV_JOB_LINK_PER_DAY", "1")
    get_settings.cache_clear()
    transport, _ = _transport()
    with _client(transport) as client:
        first = client.post("/api/job-link", json={"url": VALID_LINK})
        second = client.post("/api/job-link", json={"url": VALID_LINK})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "job_link_daily_limit"


def test_missing_posting_returns_not_found_after_one_request():
    transport, seen = _transport(guest_status=404)
    with _client(transport) as client:
        response = client.post("/api/job-link", json={"url": VALID_LINK})

    assert response.status_code == 404
    assert response.json()["code"] == "job_link_not_found"
    assert len(seen) == 1


def test_both_endpoints_rate_limited_returns_blocked_with_exact_body_keys():
    transport, seen = _transport(guest_status=429, view_status=429)
    with _client(transport) as client:
        response = client.post("/api/job-link", json={"url": VALID_LINK})

    assert response.status_code == 502
    assert response.json()["code"] == "job_link_blocked"
    assert set(response.json().keys()) == {"code", "title", "detail"}
    assert len(seen) == 2


def test_missing_url_field_returns_invalid_request():
    transport, _ = _transport()
    with _client(transport) as client:
        response = client.post("/api/job-link", json={})

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
