"""Unit tests for reading public LinkedIn job postings. All HTML here is synthetic."""

import asyncio
from collections.abc import Callable

import httpx
import pytest

from backedcv.ingestion.errors import IngestionError
from backedcv.ingestion.linkedin import (
    GUEST_URL,
    MAX_BYTES,
    VIEW_URL,
    LinkedInJob,
    canonical_url,
    fetch_linkedin_job,
    html_to_text,
    parse_job_id,
    parse_job_page,
    require_job_id,
)

JOB_ID = "4431992044"
GUEST = GUEST_URL.format(job_id=JOB_ID)
VIEW = VIEW_URL.format(job_id=JOB_ID)
Handler = Callable[[httpx.Request], httpx.Response]

# The backslash joins two physical lines of the fixture without adding whitespace to the text.
FIXTURE_HTML = """
<section class="top-card-layout">
  <h2 class="top-card-layout__title font-sans topcard__title">Junior Data Analyst</h2>
  <span class="topcard__flavor">
    <a class="topcard__org-name-link topcard__flavor--black-link" href="#">  Example Corp </a>
  </span>
  <span class="topcard__flavor topcard__flavor--bullet"> Springfield, IL </span>
  <span class="num-applicants__caption topcard__flavor--metadata topcard__flavor--bullet">
    76 applicants
  </span>
</section>
<div class="description__text description__text--rich">
  <div class="show-more-less-html__markup show-more-less-html__markup--clamp-after-5
    relative overflow-hidden">
    <p><strong>About the role</strong></p><p>We need SQL &amp; Python.</p>\
<ul><li>2+ years of SQL</li><li>Excel</li></ul>
  </div>
</div>
<ul class="description__job-criteria-list">
  <li><h3 class="description__job-criteria-subheader"> Seniority level </h3>
    <span class="description__job-criteria-text description__job-criteria-text--criteria">
      Entry level
    </span></li>
  <li><h3 class="description__job-criteria-subheader"> Employment type </h3>
    <span class="description__job-criteria-text description__job-criteria-text--criteria">
      Full-time
    </span></li>
</ul>
"""

EXPECTED_TEXT = """Junior Data Analyst
Example Corp · Springfield, IL

About the role
We need SQL & Python.
- 2+ years of SQL
- Excel

Seniority level: Entry level
Employment type: Full-time"""


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.linkedin.com/jobs/view/4431992044", "4431992044"),
        ("https://www.linkedin.com/jobs/view/4431992044/", "4431992044"),
        ("  https://www.linkedin.com/jobs/view/4431992044/  ", "4431992044"),
        (
            "https://www.linkedin.com/jobs/view/python-developer-at-example-corp-4431992044",
            "4431992044",
        ),
        ("https://www.linkedin.com/comm/jobs/view/4431992044", "4431992044"),
        ("www.linkedin.com/jobs/view/4431992044", "4431992044"),
        ("https://es.linkedin.com/jobs/view/4431992044/", "4431992044"),
        ("https://m.linkedin.com/jobs/view/4431992044", "4431992044"),
        ("https://www.linkedin.com/jobs/search/?currentJobId=4431992044", "4431992044"),
        (
            "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4431992044",
            "4431992044",
        ),
    ],
)
def test_parse_job_id_accepts_linkedin_job_links(url, expected):
    assert parse_job_id(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "https://lnkd.in/abc",
        "https://linkedin.com.evil.com/jobs/view/4431992044",
        "https://evil-linkedin.com/jobs/view/4431992044",
        "https://www.linkedin.com/in/someone",
        "ftp://www.linkedin.com/jobs/view/4431992044",
        "https://www.linkedin.com/jobs/view/443",
        "https://www.linkedin.com/jobs/search/?currentJobId=12345",
        "https://[oops/jobs/view/4431992044",
    ],
)
def test_parse_job_id_rejects_everything_else(url):
    assert parse_job_id(url) is None


def test_require_job_id_returns_the_id():
    assert require_job_id("https://www.linkedin.com/jobs/view/4431992044/") == JOB_ID


def test_require_job_id_raises_invalid_link_error():
    with pytest.raises(IngestionError) as excinfo:
        require_job_id("https://lnkd.in/abc")
    assert excinfo.value.code == "job_link_invalid"
    assert excinfo.value.status == 422


def test_canonical_url_builds_the_view_url():
    assert canonical_url(JOB_ID) == "https://www.linkedin.com/jobs/view/4431992044/"


def test_html_to_text_keeps_blocks_and_collapses_blank_lines():
    fragment = "<p>A &amp; B</p><p></p><p></p><p>C<br>D</p>"
    assert html_to_text(fragment) == "A & B\n\nC\nD"


def test_parse_job_page_reads_the_fixture():
    job = parse_job_page(FIXTURE_HTML, JOB_ID)
    assert job is not None
    assert job.job_id == JOB_ID
    assert job.title == "Junior Data Analyst"
    assert job.company == "Example Corp"
    assert job.location == "Springfield, IL"
    assert job.criteria == {"Seniority level": "Entry level", "Employment type": "Full-time"}
    assert job.closed is False
    assert "SQL & Python" in job.description
    assert "- 2+ years of SQL" in job.description


def test_parse_job_page_reads_closed_flag():
    html = FIXTURE_HTML + '<span class="closed-job__flavor--closed">No longer accepting</span>'
    job = parse_job_page(html, JOB_ID)
    assert job is not None
    assert job.closed is True


def test_parse_job_page_falls_back_to_description_text_class():
    html = '<div class="description__text"><p>Plain posting text.</p></div>'
    job = parse_job_page(html, JOB_ID)
    assert job is not None
    assert job.description == "Plain posting text."
    assert job.title == ""
    assert job.criteria == {}


@pytest.mark.parametrize(
    "html",
    [
        "",
        "   ",
        "<html><body><h2 class='top-card-layout__title'>Junior Data Analyst</h2></body></html>",
    ],
)
def test_parse_job_page_returns_none_without_description(html):
    assert parse_job_page(html, JOB_ID) is None


def test_as_text_matches_the_expected_layout():
    job = parse_job_page(FIXTURE_HTML, JOB_ID)
    assert job is not None
    assert job.as_text() == EXPECTED_TEXT


def test_as_text_skips_empty_heading_and_criteria():
    job = LinkedInJob(
        job_id=JOB_ID,
        title="",
        company="Example Corp",
        location="",
        description="Only the description.",
        criteria={},
        closed=False,
    )
    assert job.as_text() == "Example Corp\n\nOnly the description."


def _route(answers: dict[str, httpx.Response | Exception]) -> Handler:
    """Answer each URL from a fixed table; an Exception in the table is raised instead."""

    def handler(request: httpx.Request) -> httpx.Response:
        answer = answers[str(request.url)]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return handler


def _fetch(handler: Handler, requested: list[httpx.Request]) -> LinkedInJob:
    """Run fetch_linkedin_job on a mock transport that records every request it sends."""

    def record_and_answer(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return handler(request)

    async def run() -> LinkedInJob:
        transport = httpx.MockTransport(record_and_answer)
        async with httpx.AsyncClient(transport=transport) as client:
            return await fetch_linkedin_job(JOB_ID, client)

    return asyncio.run(run())


def _expect_error(handler: Handler, requested: list[httpx.Request]) -> IngestionError:
    with pytest.raises(IngestionError) as excinfo:
        _fetch(handler, requested)
    return excinfo.value


def _urls(requested: list[httpx.Request]) -> list[str]:
    return [str(request.url) for request in requested]


def test_guest_page_is_enough():
    requested: list[httpx.Request] = []
    handler = _route({GUEST: httpx.Response(200, text=FIXTURE_HTML)})
    job = _fetch(handler, requested)
    assert job.title == "Junior Data Analyst"
    assert _urls(requested) == [GUEST]


def test_view_page_is_the_fallback_after_a_rate_limit():
    requested: list[httpx.Request] = []
    handler = _route({GUEST: httpx.Response(429), VIEW: httpx.Response(200, text=FIXTURE_HTML)})
    job = _fetch(handler, requested)
    assert job.company == "Example Corp"
    assert _urls(requested) == [GUEST, VIEW]


def test_guest_not_found_stops_without_asking_the_view_page():
    requested: list[httpx.Request] = []
    handler = _route({GUEST: httpx.Response(404), VIEW: httpx.Response(200, text=FIXTURE_HTML)})
    error = _expect_error(handler, requested)
    assert (error.code, error.status) == ("job_link_not_found", 404)
    assert _urls(requested) == [GUEST]


def test_both_rate_limited_is_blocked():
    requested: list[httpx.Request] = []
    handler = _route({GUEST: httpx.Response(429), VIEW: httpx.Response(429)})
    error = _expect_error(handler, requested)
    assert (error.code, error.status) == ("job_link_blocked", 502)


def test_authwall_redirect_and_999_are_blocked():
    requested: list[httpx.Request] = []
    handler = _route(
        {
            GUEST: httpx.Response(
                302, headers={"location": "https://www.linkedin.com/authwall?trk=guest"}
            ),
            VIEW: httpx.Response(999),
        }
    )
    error = _expect_error(handler, requested)
    assert (error.code, error.status) == ("job_link_blocked", 502)


def test_timeouts_are_failed():
    requested: list[httpx.Request] = []
    handler = _route(
        {GUEST: httpx.ConnectTimeout("timeout"), VIEW: httpx.ConnectTimeout("timeout")}
    )
    error = _expect_error(handler, requested)
    assert (error.code, error.status) == ("job_link_failed", 502)


def test_page_without_description_then_server_error_is_failed():
    requested: list[httpx.Request] = []
    handler = _route(
        {
            GUEST: httpx.Response(200, text="<html><body><p>Nothing here</p></body></html>"),
            VIEW: httpx.Response(500),
        }
    )
    error = _expect_error(handler, requested)
    assert (error.code, error.status) == ("job_link_failed", 502)


def test_oversized_page_is_failed_without_parsing():
    requested: list[httpx.Request] = []
    handler = _route(
        {
            GUEST: httpx.Response(200, content=b"x" * (MAX_BYTES + 1)),
            VIEW: httpx.Response(500),
        }
    )
    error = _expect_error(handler, requested)
    assert error.code == "job_link_failed"


def test_no_request_carries_cookies():
    requested: list[httpx.Request] = []
    handler = _route(
        {
            GUEST: httpx.Response(429, headers={"set-cookie": "JSESSIONID=abc123; Path=/"}),
            VIEW: httpx.Response(
                200, text=FIXTURE_HTML, headers={"set-cookie": "bcookie=xyz; Path=/"}
            ),
        }
    )
    job = _fetch(handler, requested)
    assert job.title == "Junior Data Analyst"
    assert len(requested) == 2
    assert all("cookie" not in request.headers for request in requested)
