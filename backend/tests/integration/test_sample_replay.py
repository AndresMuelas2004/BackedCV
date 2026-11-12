"""The built-in samples replay their pinned answers in any month: no model call, same report."""

import json

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backedcv.llm import structured
from backedcv.main import create_app
from backedcv.settings import get_settings

PINNED = json.loads(
    (get_settings().samples_dir / "pinned_answers.json").read_text(encoding="utf-8")
)["samples"]


def _unreachable(**_options):
    raise RuntimeError("this call is not pinned, so it would have reached the model")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """The real cache code on an empty cache, with no way to reach the model."""
    monkeypatch.setattr(structured, "ChatAnthropic", _unreachable)
    monkeypatch.setenv("BACKEDCV_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BACKEDCV_LLM_CACHE", "true")
    monkeypatch.delenv("BACKEDCV_MODEL_FAST", raising=False)
    monkeypatch.delenv("BACKEDCV_MODEL_STRONG", raising=False)
    get_settings.cache_clear()
    with TestClient(create_app(checkpointer=InMemorySaver())) as test_client:
        yield test_client
    get_settings.cache_clear()


def _last_event(response) -> tuple[str, dict]:
    assert response.status_code == 200, response.text
    event, data = "", {}
    for block in response.text.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if fields.get("event"):
            event, data = fields["event"], json.loads(fields.get("data") or "{}")
    return event, data


def _analyse_and_optimize(client, name: str, data: dict, files: dict | None = None) -> None:
    event, report = _last_event(client.post("/api/analyses", data=data, files=files))
    assert event == "report", report
    assert report["errors"] == []
    event, result = _last_event(client.post(f"/api/analyses/{report['analysis_id']}/optimize"))
    assert event == "suggestions", result
    assert result["errors"] == []
    assert result["usage"]["cached_calls"] == result["usage"]["calls"] > 0
    assert result["score"]["fit"] == PINNED[name]["fit"]
    assert result["verdict"]["label"] == PINNED[name]["verdict"]


def test_the_hidden_risk_sample_replays_its_pinned_answers(client):
    sample = client.get("/api/samples/hidden-risk").json()
    data = {"cv_text": sample["cv_text"], "job_text": sample["job_text"].strip()}

    _analyse_and_optimize(client, "hidden_risk", data)


def test_the_curated_sample_replays_its_pinned_answers(client):
    sample = client.get("/api/samples").json()
    pdf = client.get(sample["cv_pdf_url"]).content
    files = {"cv_file": (sample["cv_filename"], pdf, "application/pdf")}

    _analyse_and_optimize(client, "curated", {"job_text": sample["job_text"].strip()}, files)
