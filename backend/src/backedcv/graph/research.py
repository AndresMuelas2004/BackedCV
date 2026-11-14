"""The deeper analysis of one posting, as a small graph of its own: three web lookups at once,
then the checks on what they found, then the plan and its messages. It keeps its state in a
thread of its own, next to the analysis it belongs to."""

import operator
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from backedcv.domain.models import JobPosting, ParsedCV
from backedcv.domain.models.research import ResearchReport, WebNotes
from backedcv.domain.research import assemble, plan_actions
from backedcv.graph.nodes import _error, _progress
from backedcv.graph.state import merge_by_id
from backedcv.llm.drafts_research import OutreachDraft, ResearchExtractDraft
from backedcv.llm.prompt_loader import load_prompt
from backedcv.llm.structured import LLMError, StructuredLLM
from backedcv.llm.web_research import WebSearcher

TOPICS: dict[str, str] = {
    "company": (
        "Find out what this company does and what matters for someone applying to this job: its "
        "product or service, its size, where it is based, the technology it works with, how it "
        "hires, and recent news. Headings: Company, Product, Size and offices, Technology, "
        "Hiring, News."
    ),
    "team": (
        "Find the people behind this posting: the person who published it or owns it when a page "
        "shows that, the manager or lead of the team the role joins, and members of that team or "
        "people in the same role at this company. Search the company's team pages, its "
        "engineering blog, talks, and public professional profiles (for example the company name "
        "with the team or the job title). Headings: Posting owner, Team lead, Team members."
    ),
    "recruiting": (
        "Find who recruits for this company and how to reach it: recruiters, talent acquisition "
        "and HR people at this company, its careers page, the page where this job is applied "
        "for, the company's profile on professional networks, and any email address for "
        "applications that a page writes out. Headings: Recruiters and HR, Careers and "
        "application pages, Email addresses."
    ),
}


class ResearchState(TypedDict, total=False):
    analysis_id: str
    job: dict  # the posting's facts; `company` is the name to look up
    job_text: str
    cv: dict
    assessments: dict
    notes: Annotated[dict, merge_by_id]  # topic -> WebNotes
    report: dict | None
    errors: Annotated[list, operator.add]
    usage: Annotated[list, operator.add]


class LookupTask(TypedDict):
    topic: str
    data: str


def research_thread(analysis_id: str) -> str:
    """The checkpoint thread, and the run lock, of an analysis's deeper analysis."""
    return f"{analysis_id}:research"


def research_config(analysis_id: str) -> dict:
    return {
        "configurable": {"thread_id": research_thread(analysis_id)},
        "max_concurrency": 4,
        "run_name": "research",
        "metadata": {"analysis_id": analysis_id},
    }


def _job_block(job: JobPosting) -> str:
    return (
        "<job>\n"
        f"company: {job.company or 'unknown'}\n"
        f"title: {job.title or 'unknown'}\n"
        f"location: {job.location or 'unknown'}\n"
        "</job>"
    )


def _lookup_data(state: ResearchState, topic: str) -> str:
    job = JobPosting.model_validate(state["job"])
    return (
        f"<task>\n{TOPICS[topic]}\n</task>\n\n{_job_block(job)}\n\n"
        f"<job_posting>\n{state['job_text']}\n</job_posting>"
    )


def _extract_data(job: JobPosting, job_text: str, notes: dict[str, WebNotes]) -> str:
    blocks = [_job_block(job)]
    for topic in TOPICS:
        text = notes.get(topic, WebNotes()).text or "Nothing was found."
        blocks.append(f'<notes topic="{topic}">\n{text}\n</notes>')
    # Every page once per address, so the model sees each one a single time.
    pages: dict[str, str] = {}
    for topic in TOPICS:
        for source in notes.get(topic, WebNotes()).sources:
            pages.setdefault(source.url, f"{source.url} | {source.title}")
    rows = "\n".join(pages.values()) or "none"
    blocks.append(f"<pages>\n{rows}\n</pages>")
    blocks.append(f"<job_posting>\n{job_text}\n</job_posting>")
    return "\n\n".join(blocks)


def _outreach_data(
    job: JobPosting,
    cv: ParsedCV,
    assessments: dict,
    report: ResearchReport,
) -> str:
    requirements = [
        f"{req.id} | {req.label} | {assessments.get(req.id, {}).get('status', 'unknown')}"
        for req in job.requirements
    ]
    people = [f"{p.id} | {p.name} | {p.role} | {p.group}" for p in report.people]
    channels = [f"{c.id} | {c.kind} | {c.label} | {c.value}" for c in report.channels]
    blocks = [
        _job_block(job),
        _tagged("requirements", requirements),
        f"<cv>\n{cv.numbered()}\n</cv>",
        _tagged("people", people),
        _tagged("channels", channels),
    ]
    return "\n\n".join(blocks)


def _tagged(tag: str, rows: list[str]) -> str:
    """The rows inside a tag, one per line; `none` when there are none."""
    body = "\n".join(rows) or "none"
    return f"<{tag}>\n{body}\n</{tag}>"


def make_research_nodes(
    llm: StructuredLLM, searcher: WebSearcher, searches_per_step: int = 3
) -> dict[str, Callable]:
    async def plan(state: ResearchState) -> dict:
        _progress("plan", "started")
        _progress("plan", "done")
        return {}

    def route_lookups(state: ResearchState) -> list[Send]:
        return [
            Send("lookup", {"topic": topic, "data": _lookup_data(state, topic)}) for topic in TOPICS
        ]

    async def lookup(task: LookupTask) -> dict:
        topic = task["topic"]
        _progress("search", "started", topic=topic)
        try:
            notes, usage = await searcher.search(
                load_prompt("research_web"),
                task["data"],
                node=f"research_{topic}",
                max_searches=searches_per_step,
            )
        except Exception as exc:  # a failed lookup leaves its topic empty; the run goes on
            _progress("search", "done", topic=topic)
            return {
                "notes": {topic: WebNotes().model_dump()},
                "errors": [_error(f"research_{topic}", exc)],
            }
        _progress("search", "done", topic=topic)
        return {"notes": {topic: notes.model_dump()}, "usage": [usage]}

    async def extract(state: ResearchState) -> dict:
        _progress("extract", "started")
        job = JobPosting.model_validate(state["job"])
        notes = {topic: WebNotes.model_validate(row) for topic, row in state["notes"].items()}
        # Nothing to check the people and the addresses against: no model call would help.
        if not any(item.text or item.sources for item in notes.values()):
            raise LLMError("research: every web lookup failed")
        draft, usage = await llm.run(
            load_prompt("research_extract"),
            _extract_data(job, state["job_text"], notes),
            ResearchExtractDraft,
            node="research_extract",
        )
        findings = assemble(draft, [notes[t] for t in TOPICS if t in notes], state["job_text"])
        report = ResearchReport(
            company=findings.company,
            people=findings.people,
            channels=findings.channels,
            actions=[],
            notes=findings.notes,
            sources=findings.sources,
            searches=sum(item.searches for item in notes.values()),
            created_at=datetime.now(UTC).isoformat(),
        )
        _progress("extract", "done", people=len(findings.people))
        return {"report": report.model_dump(), "usage": [usage]}

    async def outreach(state: ResearchState) -> dict:
        _progress("drafts", "started")
        report = ResearchReport.model_validate(state["report"])
        job = JobPosting.model_validate(state["job"])
        cv = ParsedCV.model_validate(state["cv"])
        try:
            draft, usage = await llm.run(
                load_prompt("write_outreach"),
                _outreach_data(job, cv, state.get("assessments") or {}, report),
                OutreachDraft,
                node="write_outreach",
            )
            actions = plan_actions(draft, report.people, report.channels, cv)
        except Exception as exc:  # the people, the channels and the notes stay even so
            _progress("drafts", "done", actions=0)
            failed = report.model_copy(
                update={
                    "notes": [
                        *report.notes,
                        "The plan and the messages could not be written.",
                    ]
                }
            )
            return {
                "report": failed.model_dump(),
                "errors": [_error("write_outreach", exc)],
            }
        _progress("drafts", "done", actions=len(actions))
        done = report.model_copy(update={"actions": actions})
        return {"report": done.model_dump(), "usage": [usage]}

    return {
        "plan": plan,
        "route_lookups": route_lookups,
        "lookup": lookup,
        "extract": extract,
        "outreach": outreach,
    }


def build_research_graph(
    llm: StructuredLLM,
    searcher: WebSearcher,
    checkpointer=None,
    searches_per_step: int = 3,
):
    nodes = make_research_nodes(llm, searcher, searches_per_step)
    graph = StateGraph(ResearchState)
    graph.add_node("plan", nodes["plan"])
    graph.add_node("lookup", nodes["lookup"])
    graph.add_node("extract", nodes["extract"])
    graph.add_node("outreach", nodes["outreach"])

    # The three lookups run in one step; extract waits for all of them.
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", nodes["route_lookups"], ["lookup"])
    graph.add_edge("lookup", "extract")
    graph.add_edge("extract", "outreach")
    graph.add_edge("outreach", END)
    return graph.compile(checkpointer=checkpointer)
