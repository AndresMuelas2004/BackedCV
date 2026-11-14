"""The deeper analysis of a posting: who is behind it and how to reach them.

It runs beside the analysis, in a thread and under a lock of its own, so the report stays usable
meanwhile.
"""

from collections.abc import AsyncIterable
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, StringConstraints

from backedcv.api.errors import ApiError, analysis_not_found
from backedcv.api.rate_limit import client_address
from backedcv.api.runs import Run, stream_graph
from backedcv.graph.builder import run_config
from backedcv.graph.research import research_config, research_thread
from backedcv.settings import get_settings

router = APIRouter(tags=["research"])

RESEARCH_FAILED = ("research_failed", "The deeper analysis could not finish.")


class ResearchRequest(BaseModel):
    # The company to look up, when the posting does not name it.
    company: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = None


async def _view(request: Request, analysis_id: str, *, finished: bool = False) -> dict:
    """What the frontend sees. `finished` is set by the run itself, which still holds the lock
    while it reads the result, so the running check is skipped then."""
    graph, runs = request.app.state.research_graph, request.app.state.runs
    key = research_thread(analysis_id)
    report = None
    if graph is not None:
        snapshot = await graph.aget_state(research_config(analysis_id))
        report = (snapshot.values or {}).get("report")
    failure = runs.failure(key)
    if not finished and runs.is_running(key):
        status = "running"
    elif failure is not None:
        status = "failed"
    else:
        status = "done" if report else "none"
    return {
        "status": status,
        "available": graph is not None and get_settings().research_enabled,
        "report": report if status == "done" else None,
        "error": failure if status == "failed" else None,
    }


@router.get("/analyses/{analysis_id}/research")
async def get_research(request: Request, analysis_id: str) -> dict:
    snapshot = await request.app.state.graph.aget_state(run_config(analysis_id))
    if not snapshot.values:
        raise analysis_not_found()
    return await _view(request, analysis_id)


async def start_research(
    request: Request, analysis_id: str, body: ResearchRequest | None = None
) -> Run:
    """Starts the deeper analysis. Every refusal is decided here, before the stream opens, so it
    arrives as a JSON error."""
    settings = get_settings()
    graph = request.app.state.research_graph
    if graph is None or not settings.research_enabled:
        raise ApiError(
            503, "research_unavailable", "The deeper analysis is not available on this server."
        )
    key = research_thread(analysis_id)
    locks = request.app.state.locks
    locks.acquire(key)  # 409 while the deeper analysis already runs
    try:
        snapshot = await request.app.state.graph.aget_state(run_config(analysis_id))
        values = snapshot.values
        if not values:
            raise analysis_not_found()
        job = values.get("job")
        if not job or not values.get("cv"):
            raise ApiError(409, "wrong_stage", "The deeper analysis needs a finished report.")
        company = ((body.company if body else None) or job.get("company") or "").strip()
        if not company:
            raise ApiError(
                422,
                "company_unknown",
                "The posting does not name the company.",
                "Without the company's name there is nothing to look up.",
            )
        request.app.state.research_limiter.check(client_address(request))
        initial = {
            "analysis_id": analysis_id,
            "job": {**job, "company": company},
            "job_text": values.get("job_text") or "",
            "cv": values["cv"],
            "assessments": values.get("assessments") or {},
            "notes": {},
            "report": None,
        }
    except BaseException:
        locks.release(key)
        raise

    async def work(run: Run) -> dict:
        # A new run starts from nothing: what an earlier run found is not mixed in.
        await request.app.state.checkpointer.adelete_thread(key)
        await stream_graph(graph, initial, research_config(analysis_id), run)
        return await _view(request, analysis_id, finished=True)

    return request.app.state.runs.launch(key, work, done="research", failed=RESEARCH_FAILED)


@router.post(
    "/analyses/{analysis_id}/research",
    response_class=EventSourceResponse,
)
async def research(
    run: Annotated[Run, Depends(start_research)],
) -> AsyncIterable[ServerSentEvent]:
    """Streams the `progress` steps, then `research` (or `error`)."""
    async with aclosing(run.listen()) as events:
        async for event in events:
            yield event
