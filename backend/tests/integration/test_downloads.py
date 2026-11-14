import io
import json
from datetime import UTC, datetime, timedelta

import docx
import pdfplumber
import pytest
import typst
from docx.enum.text import WD_ALIGN_PARAGRAPH
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backedcv.api.routes.downloads import download_name
from backedcv.domain.models import CVDocument, DocContact
from backedcv.ingestion import read_cv
from backedcv.main import create_app
from tests.fakes import CV_TEXT, JOB_TEXT
from tests.fakes_optimize import FakeOptimizeLLM

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

# A one-page CV in the look of a real uploaded file: a centred bold name, a rule under each
# heading, bullets and a date line. Its nine lines read as CV_TEXT does.
CV_PDF_SOURCE = r"""#set page(width: 595pt, height: 842pt, margin: 40pt)
#set text(font: "Libertinus Serif", size: 10pt)
#set par(leading: 4pt, spacing: 8pt)
#align(center)[#text(size: 18pt, weight: "bold")[Jane Doe]]
#align(center)[Madrid, Spain · jane\@example.com · +34 600 123 456]
*EXPERIENCE*
#line(length: 100%, stroke: 0.6pt)
*Data Engineer, Acme Corp*

Jan 2021 - Present
- Built ETL pipelines in Python and SQL on AWS
- Built a support bot with LangGraph
*EDUCATION*
#line(length: 100%, stroke: 0.6pt)
BSc Computer Science, Universidad Example, 2020
"""
CV_PDF = typst.compile(CV_PDF_SOURCE.encode(), format="pdf", ignore_system_fonts=True)


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


def _built_from_pdf(client) -> str:
    """A CV read from a PDF, so the built CV has the look of that file."""
    response = client.post(
        "/api/analyses",
        data={"job_text": JOB_TEXT},
        files={"cv_file": ("cv.pdf", CV_PDF, "application/pdf")},
    )
    analysis_id = _events(response.text)[-1][1]["analysis_id"]
    client.post(f"/api/analyses/{analysis_id}/optimize")
    response = client.post(f"/api/analyses/{analysis_id}/build", json={"accepted": ["S01"]})
    assert _events(response.text)[-1][0] == "built"
    return analysis_id


def test_the_cv_pdf_reads_as_the_cv_text():
    lines = [line.text for line in read_cv(CV_PDF, "cv.pdf").lines]

    assert len(lines) == 9
    for got, want in zip(lines, CV_TEXT.strip().splitlines(), strict=True):
        assert got.split()[:2] == want.split()[:2]


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
        "style": "standard",
        "styles": ["standard"],
        "original_pages": None,
        "columns": 1,
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


def test_a_cv_read_from_a_pdf_is_offered_in_its_own_look(client):
    analysis_id = _built_from_pdf(client)

    layout = client.get(f"/api/analyses/{analysis_id}/cv-layout").json()

    assert layout["style"] == "original"
    assert layout["styles"] == ["original", "standard"]
    assert (layout["original_pages"], layout["pages"], layout["fits"]) == (1, 1, True)
    standard = client.get(
        f"/api/analyses/{analysis_id}/cv-layout", params={"style": "standard"}
    ).json()
    assert standard["style"] == "standard"
    assert standard["styles"] == ["original", "standard"]


def test_the_pdf_keeps_the_look_of_the_uploaded_file(client):
    analysis_id = _built_from_pdf(client)

    pdf = client.get(f"/api/analyses/{analysis_id}/cv.pdf")

    assert pdf.status_code == 200
    with pdfplumber.open(io.BytesIO(pdf.content)) as opened:
        words = opened.pages[0].extract_words(extra_attrs=["fontname"])
    jane = next(word for word in words if word["text"] == "Jane")
    doe = next(word for word in words if word["text"] == "Doe")
    assert "Bold" in jane["fontname"] and "Bold" in doe["fontname"]
    assert abs((jane["x0"] + doe["x1"]) / 2 - 297.5) < 3


def test_the_standard_pdf_is_the_plain_template(client):
    analysis_id = _built_from_pdf(client)

    pdf = client.get(f"/api/analyses/{analysis_id}/cv.pdf", params={"style": "standard"})

    with pdfplumber.open(io.BytesIO(pdf.content)) as opened:
        words = opened.pages[0].extract_words()
    jane = next(word for word in words if word["text"] == "Jane")
    assert jane["x0"] < 100


def test_the_pdf_holds_the_accepted_rewrite(client):
    analysis_id = _built_from_pdf(client)

    pdf = client.get(f"/api/analyses/{analysis_id}/cv.pdf")

    with pdfplumber.open(io.BytesIO(pdf.content)) as opened:
        text = "\n".join(page.extract_text() or "" for page in opened.pages)
    assert "agent frameworks (LangGraph)" in text


def test_the_docx_keeps_the_look_of_the_uploaded_file(client):
    analysis_id = _built_from_pdf(client)

    response = client.get(f"/api/analyses/{analysis_id}/cv.docx")

    document = docx.Document(io.BytesIO(response.content))
    first = document.paragraphs[0]
    assert first.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert first.text == "Jane Doe"


def test_the_build_report_of_the_pdf_cv_reads_back(client):
    analysis_id = _built_from_pdf(client)

    projection = client.get(f"/api/analyses/{analysis_id}").json()

    assert projection["build_report"]["roundtrip_ok"] is True


def test_the_projection_hides_the_look_of_the_uploaded_file(client):
    analysis_id = _built_from_pdf(client)

    projection = client.get(f"/api/analyses/{analysis_id}").json()

    assert all("fmt" not in line for line in projection["cv"]["lines"])
    assert "layout" not in projection["cv_meta"]
