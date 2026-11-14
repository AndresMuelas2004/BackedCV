"""The deeper analysis over HTTP: the stream, the stored result, the limits and the clean-up."""

import json

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backedcv.api.rate_limit import RunLimiter
from backedcv.main import create_app
from tests.fakes import CV_TEXT, JOB_TEXT
from tests.fakes_research import FakeResearchLLM, FakeSearcher


def _client(searcher=None) -> TestClient:
    return TestClient(
        create_app(llm=FakeResearchLLM(), checkpointer=InMemorySaver(), searcher=searcher)
    )


@pytest.fixture
def client():
    with _client(FakeSearcher()) as c:
        yield c


def _events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line and line[0] != ":"
        )
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def _analysis_id(client) -> str:
    response = client.post("/api/analyses", data={"cv_text": CV_TEXT, "job_text": JOB_TEXT})
    return _events(response.text)[-1][1]["analysis_id"]


def _run(client, analysis_id: str):
    response = client.post(f"/api/analyses/{analysis_id}/research")
    return response, _events(response.text)


def test_before_a_run_nothing_is_stored(client):
    analysis_id = _analysis_id(client)

    body = client.get(f"/api/analyses/{analysis_id}/research").json()

    assert body["status"] == "none"
    assert body["available"] is True
    assert body["report"] is None


def test_the_run_streams_its_steps_and_ends_with_the_report(client):
    analysis_id = _analysis_id(client)

    response, events = _run(client, analysis_id)

    assert response.status_code == 200
    progress = [data for name, data in events if name == "progress"]
    assert {"plan", "extract", "drafts"} <= {data["step"] for data in progress}
    started = [
        data["topic"]
        for data in progress
        if data["step"] == "search" and data["status"] == "started"
    ]
    assert sorted(started) == ["company", "recruiting", "team"]
    name, final = events[-1]
    assert name == "research"
    assert final["status"] == "done"
    report = final["report"]
    assert [(p["id"], p["name"]) for p in report["people"]] == [("P01", "Jane Roe")]
    assert any(channel["kind"] == "careers_page" for channel in report["channels"])
    drafts = [action["draft"] or {} for action in report["actions"]]
    assert any("Jane Doe" in (draft.get("body") or "") for draft in drafts)


def test_the_stored_result_is_the_same_after_the_run(client):
    analysis_id = _analysis_id(client)
    _run(client, analysis_id)

    body = client.get(f"/api/analyses/{analysis_id}/research").json()

    assert body["status"] == "done"
    assert [p["name"] for p in body["report"]["people"]] == ["Jane Roe"]


def test_the_run_leaves_the_analysis_untouched(client):
    analysis_id = _analysis_id(client)
    _run(client, analysis_id)

    projection = client.get(f"/api/analyses/{analysis_id}").json()

    assert projection["stage"] == "report_ready"


def test_an_unknown_analysis_is_404(client):
    get = client.get("/api/analyses/does-not-exist/research")
    post = client.post("/api/analyses/does-not-exist/research")

    assert (get.status_code, get.json()["code"]) == (404, "not_found")
    assert (post.status_code, post.json()["code"]) == (404, "not_found")


def test_without_a_searcher_the_run_is_unavailable():
    with _client() as client:
        analysis_id = _analysis_id(client)

        body = client.get(f"/api/analyses/{analysis_id}/research").json()
        response = client.post(f"/api/analyses/{analysis_id}/research")

    assert body["available"] is False
    assert (response.status_code, response.json()["code"]) == (503, "research_unavailable")


def test_the_hourly_limit_refuses_the_second_run(client):
    client.app.state.research_limiter = RunLimiter(
        per_hour=1,
        per_day=10,
        hourly_code="research_rate_limited",
    )
    analysis_id = _analysis_id(client)
    first, _ = _run(client, analysis_id)
    second = client.post(f"/api/analyses/{analysis_id}/research")

    assert first.status_code == 200
    assert (second.status_code, second.json()["code"]) == (429, "research_rate_limited")


def test_a_run_whose_lookups_all_fail_ends_with_an_error():
    with _client(FakeSearcher(failing=("company", "team", "recruiting"))) as client:
        analysis_id = _analysis_id(client)

        _, events = _run(client, analysis_id)
        body = client.get(f"/api/analyses/{analysis_id}/research").json()

    name, data = events[-1]
    assert (name, data["code"]) == ("error", "research_failed")
    assert body["status"] == "failed"
    assert body["error"]["code"] == "research_failed"


def test_a_second_run_replaces_the_first(client):
    analysis_id = _analysis_id(client)
    _run(client, analysis_id)
    _, events = _run(client, analysis_id)

    assert events[-1][0] == "research"
    body = client.get(f"/api/analyses/{analysis_id}/research").json()
    assert [p["name"] for p in body["report"]["people"]] == ["Jane Roe"]


def test_deleting_the_analysis_removes_its_deeper_analysis(client):
    analysis_id = _analysis_id(client)
    _run(client, analysis_id)

    deleted = client.delete(f"/api/analyses/{analysis_id}")

    assert deleted.status_code == 204
    gone = client.get(f"/api/analyses/{analysis_id}/research")
    assert (gone.status_code, gone.json()["code"]) == (404, "not_found")


def test_a_company_longer_than_the_limit_is_refused(client):
    analysis_id = _analysis_id(client)

    response = client.post(f"/api/analyses/{analysis_id}/research", json={"company": "x" * 200})

    assert response.status_code == 422
