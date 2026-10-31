"""Read a LinkedIn job posting from its link, as an anonymous visitor (no login, no cookies)."""

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backedcv.ingestion.linkedin import canonical_url, fetch_linkedin_job, require_job_id

router = APIRouter(tags=["job-link"])


class JobLinkRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


@router.post("/job-link")
async def read_job_link(request: Request, body: JobLinkRequest) -> dict:
    job_id = require_job_id(body.url)  # an invalid link is refused before it uses any quota
    client = request.client.host if request.client else "unknown"
    request.app.state.job_link_limiter.check(client)
    async with httpx.AsyncClient(transport=request.app.state.job_link_transport) as http:
        job = await fetch_linkedin_job(job_id, http)
    return {
        "job_id": job.job_id,
        "url": canonical_url(job.job_id),
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "closed": job.closed,
        "text": job.as_text(),
    }
