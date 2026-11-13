import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backedcv.api.routes.downloads import download_name
from backedcv.domain.models import CVDocument, DocContact
from backedcv.main import create_app
from tests.fakes import CV_TEXT, JOB_TEXT
from tests.fakes_optimize import FakeOptimizeLLM

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def client():
    with TestClient(create_app(llm=FakeOptimizeLLM(), checkpointer=InMemorySaver())) as c:
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


def _built(client) -> str:
    analysis_id = _analysis_id(client)
    client.post(f"/api/analyses/{analysis_id}/optimize")
    response = client.post(f"/api/analyses/{analysis_id}/build", json={"accepted": ["S01"]})
    assert _events(response.text)[-1][0] == "built"
    return analysis_id


def test_the_cv_cannot_be_downloaded_before_the_build(client):
    analysis_id = _analysis_id(client)

    for name in ("cv.docx", "cv.pdf"):
        response = client.get(f"/api/analyses/{analysis_id}/{name}")
        assert (response.status_code, response.json()["code"]) == (409, "not_built")


def test_the_built_cv_downloads_as_docx_and_pdf(client):
    analysis_id = _built(client)

    docx = client.get(f"/api/analyses/{analysis_id}/cv.docx")
    pdf = client.get(f"/api/analyses/{analysis_id}/cv.pdf")

    assert docx.status_code == 200
    assert docx.content.startswith(b"PK")
    assert docx.headers["content-type"] == DOCX_TYPE
    assert docx.headers["content-disposition"] == 'attachment; filename="Jane-Doe-CV.docx"'
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-disposition"] == 'attachment; filename="Jane-Doe-CV.pdf"'


def test_downloads_of_an_unknown_analysis_are_404(client):
    response = client.get("/api/analyses/does-not-exist/cv.pdf")

    assert (response.status_code, response.json()["code"]) == (404, "not_found")


def test_delete_removes_the_analysis_and_its_checkpoints(client):
    analysis_id = _analysis_id(client)

    response = client.delete(f"/api/analyses/{analysis_id}")

    assert response.status_code == 204
    assert response.content == b""
    gone = client.get(f"/api/analyses/{analysis_id}")
    assert (gone.status_code, gone.json()["code"]) == (404, "not_found")
    assert client.delete(f"/api/analyses/{analysis_id}").status_code == 404
    ledger = client.app.state.ledger
    assert analysis_id not in ledger.created_before(datetime.now(UTC) + timedelta(days=1))


def test_delete_is_refused_while_a_run_holds_the_analysis(client):
    analysis_id = _analysis_id(client)
    locks = client.app.state.locks
    locks.acquire(analysis_id)
    try:
        response = client.delete(f"/api/analyses/{analysis_id}")
    finally:
        locks.release(analysis_id)

    assert (response.status_code, response.json()["code"]) == (409, "run_in_progress")
    assert client.get(f"/api/analyses/{analysis_id}").status_code == 200


def test_the_layout_says_how_many_pages_the_cv_takes(client):
    analysis_id = _built(client)

    layout = client.get(f"/api/analyses/{analysis_id}/cv-layout").json()
    limited = client.get(f"/api/analyses/{analysis_id}/cv-layout", params={"max_pages": 1}).json()

    assert layout == {
        "pages": 1,
        "max_pages": None,
        "fits": True,
        "font_size": 10.5,
        "standard_font_size": 10.5,
    }
    assert (limited["max_pages"], limited["fits"]) == (1, True)


def test_both_downloads_take_a_page_limit_and_refuse_a_wrong_one(client):
    analysis_id = _built(client)

    pdf = client.get(f"/api/analyses/{analysis_id}/cv.pdf", params={"max_pages": 1})
    docx = client.get(f"/api/analyses/{analysis_id}/cv.docx", params={"max_pages": 2})
    refused = client.get(f"/api/analyses/{analysis_id}/cv.pdf", params={"max_pages": 9})

    assert (pdf.status_code, docx.status_code) == (200, 200)
    assert (refused.status_code, refused.json()["code"]) == (422, "invalid_request")


def test_the_layout_needs_a_built_cv(client):
    analysis_id = _analysis_id(client)

    response = client.get(f"/api/analyses/{analysis_id}/cv-layout")

    assert (response.status_code, response.json()["code"]) == (409, "not_built")


def test_the_download_is_named_after_the_candidate():
    named = CVDocument(contact=DocContact(name="José Muñoz-Peña"))

    assert download_name(named, "pdf") == "Jose-Munoz-Pena-CV.pdf"
    assert download_name(CVDocument(), "docx") == "CV.docx"
