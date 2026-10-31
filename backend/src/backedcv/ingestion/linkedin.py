"""Read a public LinkedIn job posting as an anonymous visitor: no login, no cookies, no key."""

import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, urlsplit

import httpx
import lxml.etree
import lxml.html

from backedcv.ingestion.errors import IngestionError

GUEST_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
VIEW_URL = "https://www.linkedin.com/jobs/view/{job_id}/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 10.0  # seconds per request
MAX_BYTES = 3_000_000
BLOCK_MARKERS = ("authwall", "login", "signup", "checkpoint")

_REDIRECT_CODES = {301, 302, 303, 307, 308}
_QUERY_ID = re.compile(r"\d{6,15}", re.ASCII)
_PATH_ID = re.compile(r"/jobs/view/(?:[^/]*?-)?(\d{6,15})(?:/|$)", re.ASCII)
_DESCRIPTION_XPATHS = (
    "//div[contains(concat(' ', normalize-space(@class), ' '), ' show-more-less-html__markup ')]",
    "//div[contains(@class, 'description__text')]",
)
_TITLE_XPATHS = ("//*[contains(@class, 'top-card-layout__title')]", "//h1")
_COMPANY_XPATHS = (
    "//a[contains(@class, 'topcard__org-name-link')]",
    "//*[contains(@class, 'topcard__org-name')]",
)
_LOCATION_XPATHS = (
    "//span[contains(@class, 'topcard__flavor--bullet')"
    " and not(contains(@class, 'num-applicants__caption'))]",
)
_CRITERIA_KEYS = "//h3[contains(@class, 'description__job-criteria-subheader')]"
_CRITERIA_VALUES = "//span[contains(@class, 'description__job-criteria-text')]"


@dataclass(frozen=True)
class LinkedInJob:
    """A job posting read from LinkedIn, as plain text."""

    job_id: str
    title: str
    company: str
    location: str
    description: str
    criteria: dict[str, str]  # e.g. {"Seniority level": "Entry level"}
    closed: bool  # LinkedIn says it no longer accepts applications

    def as_text(self) -> str:
        """Render the posting as plain text: heading, description, then the criteria."""
        company_line = " · ".join(part for part in (self.company, self.location) if part)
        heading = "\n".join(part for part in (self.title, company_line) if part)
        criteria = "\n".join(f"{key}: {value}" for key, value in self.criteria.items())
        return "\n\n".join(block for block in (heading, self.description, criteria) if block)


def canonical_url(job_id: str) -> str:
    """Return the public view URL of a job ID."""
    return VIEW_URL.format(job_id=job_id)


def parse_job_id(url: str) -> str | None:
    """Return the job ID in a LinkedIn job link, or None. The link is parsed, never fetched."""
    url = url.strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = parts.hostname or ""
    if parts.scheme not in ("http", "https"):
        return None
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None
    current_job_id = parse_qs(parts.query).get("currentJobId", [""])[0]
    if _QUERY_ID.fullmatch(current_job_id):
        return current_job_id
    match = _PATH_ID.search(parts.path)
    return match.group(1) if match else None


def require_job_id(url: str) -> str:
    """Return the job ID in a LinkedIn job link, or raise job_link_invalid."""
    job_id = parse_job_id(url)
    if job_id is None:
        raise IngestionError(
            "job_link_invalid",
            "This is not a LinkedIn job link.",
            "Use a link such as https://www.linkedin.com/jobs/view/1234567890/, "
            "or paste the posting text instead.",
            status=422,
        )
    return job_id


def html_to_text(fragment: str) -> str:
    """Turn an HTML fragment into plain text, one line per block, without runs of blank lines."""
    text = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    text = re.sub(r"(?i)</(p|div|li|ul|ol|h[1-6])>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    lines: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if line or (lines and lines[-1]):
            lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def parse_job_page(html: str, job_id: str) -> LinkedInJob | None:
    """Read a posting from LinkedIn page HTML, or return None if it has no usable description."""
    if not html.strip():
        return None
    try:
        tree = lxml.html.fromstring(html)
    except (lxml.etree.ParserError, ValueError):
        return None
    description_el = _first(tree, *_DESCRIPTION_XPATHS)
    if description_el is None:
        return None
    description = html_to_text(lxml.html.tostring(description_el, encoding="unicode"))
    if not description:
        return None
    return LinkedInJob(
        job_id=job_id,
        title=_short_text(tree, *_TITLE_XPATHS),
        company=_short_text(tree, *_COMPANY_XPATHS),
        location=_short_text(tree, *_LOCATION_XPATHS),
        description=description,
        criteria=_criteria(tree),
        closed="closed-job__flavor--closed" in html,
    )


def _first(tree: lxml.html.HtmlElement, *xpaths: str) -> lxml.html.HtmlElement | None:
    """Return the first element matched by the first XPath that matches anything."""
    for xpath in xpaths:
        found = tree.xpath(xpath)
        if found:
            return found[0]
    return None


def _short_text(tree: lxml.html.HtmlElement, *xpaths: str) -> str:
    """Return the whitespace-normalized text of the first match, or an empty string."""
    el = _first(tree, *xpaths)
    return " ".join(el.text_content().split()) if el is not None else ""


def _criteria(tree: lxml.html.HtmlElement) -> dict[str, str]:
    """Pair the criteria headings with their values, in page order."""
    keys = [" ".join(el.text_content().split()) for el in tree.xpath(_CRITERIA_KEYS)]
    values = [" ".join(el.text_content().split()) for el in tree.xpath(_CRITERIA_VALUES)]
    return {key: value for key, value in zip(keys, values, strict=False) if key and value}


async def fetch_linkedin_job(job_id: str, client: httpx.AsyncClient) -> LinkedInJob:
    """Read a posting from the guest page, then the full page; raise IngestionError if both fail."""
    outcomes: list[str] = []
    for template in (GUEST_URL, VIEW_URL):
        job, outcome = await _attempt(client, template.format(job_id=job_id), job_id)
        if job is not None:
            return job
        outcomes.append(outcome)
        if outcome == "not_found":
            break
    raise _failure(outcomes)


async def _attempt(
    client: httpx.AsyncClient, url: str, job_id: str
) -> tuple[LinkedInJob | None, str]:
    """Request one URL; return the job, or the outcome: not_found, blocked or failed."""
    client.cookies.clear()  # the anonymous visitor never sends cookies
    try:
        response = await client.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=False)
    except httpx.HTTPError:
        return None, "failed"
    status = response.status_code
    if status == 200:
        if len(response.content) > MAX_BYTES:
            return None, "failed"
        job = parse_job_page(response.text, job_id)
        if job is not None:
            return job, "ok"
        return None, "blocked" if _has_block_marker(response.text) else "failed"
    if status in _REDIRECT_CODES:
        location = response.headers.get("location", "")
        return None, "blocked" if _has_block_marker(location) else "not_found"
    if status in (404, 410):
        return None, "not_found"
    if status in (403, 429, 999):
        return None, "blocked"
    return None, "failed"


def _has_block_marker(text: str) -> bool:
    """Tell whether a response points at a login or challenge wall."""
    lowered = text.lower()
    return any(marker in lowered for marker in BLOCK_MARKERS)


def _failure(outcomes: list[str]) -> IngestionError:
    """Pick the error to report: not_found beats blocked, and blocked beats failed."""
    if "not_found" in outcomes:
        return IngestionError(
            "job_link_not_found",
            "LinkedIn has no public posting at this link.",
            "The posting may have been removed. Paste the posting text instead.",
            status=404,
        )
    if "blocked" in outcomes:
        return IngestionError(
            "job_link_blocked",
            "LinkedIn did not let the server read this posting.",
            "LinkedIn refuses some automatic requests. Paste the posting text instead.",
            status=502,
        )
    return IngestionError(
        "job_link_failed",
        "The posting could not be read from LinkedIn.",
        "Paste the posting text instead.",
        status=502,
    )
