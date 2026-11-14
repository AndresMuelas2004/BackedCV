"""The deeper analysis graph: the lookups, the checks and the plan, with canned answers."""

import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backedcv.domain.builders import build_parsed_cv
from backedcv.domain.models import JobPosting
from backedcv.domain.models.research import ResearchReport
from backedcv.graph.research import TOPICS, build_research_graph, research_config, research_thread
from backedcv.ingestion import read_cv_text
from backedcv.llm.structured import LLMError
from tests.fakes import CV_TEXT, JOB_TEXT, structure_draft
from tests.fakes_research import PROFILE, FakeResearchLLM, FakeSearcher


def initial_state() -> dict:
    cv = build_parsed_cv(read_cv_text(CV_TEXT).lines, structure_draft())
    job = JobPosting(
        title="Junior Data Engineer", company="Example Analytics", location="New York, NY"
    )
    return {
        "analysis_id": "a1",
        "job": job.model_dump(),
        "job_text": JOB_TEXT,
        "cv": cv.model_dump(),
        "assessments": {},
        "notes": {},
        "report": None,
    }


def run(searcher: FakeSearcher, llm: FakeResearchLLM | None = None) -> dict:
    graph = build_research_graph(llm or FakeResearchLLM(), searcher, checkpointer=InMemorySaver())
    return asyncio.run(graph.ainvoke(initial_state(), research_config("a1")))


def test_report_keeps_the_verified_person_and_leaves_out_the_invented_one():
    result = run(FakeSearcher())
    report = ResearchReport.model_validate(result["report"])

    assert [(p.id, p.name) for p in report.people] == [("P01", "Jane Roe")]
    assert report.people[0].profile_url == PROFILE
    assert "John Ghost" not in [p.name for p in report.people]
    assert "No recruiter was found for this company." in report.notes
    assert "1 person was left out because no page from the searches shows them." in report.notes


def test_plan_holds_the_apply_and_connect_steps_with_the_name_filled_in():
    result = run(FakeSearcher())
    report = ResearchReport.model_validate(result["report"])

    assert [a.kind for a in report.actions] == ["apply", "connect"]
    connect = report.actions[1]
    assert connect.draft is not None
    assert connect.draft.body.endswith("Jane Doe")
    assert "[Your name]" not in connect.draft.body
    assert "L006" in connect.draft.evidence


def test_three_searches_and_five_usage_records():
    result = run(FakeSearcher())
    report = ResearchReport.model_validate(result["report"])

    # Three lookups, the extract and the outreach: each one reports its usage.
    assert report.searches == 3
    assert len(result["usage"]) == 5


def test_each_lookup_gets_the_task_of_its_topic_and_the_posting():
    searcher = FakeSearcher()
    run(searcher)

    assert len(searcher.calls) == 3
    for node, data in searcher.calls:
        topic = node.removeprefix("research_")
        assert topic in TOPICS
        assert TOPICS[topic] in data
        assert JOB_TEXT.strip() in data


def test_a_failed_lookup_does_not_stop_the_run():
    result = run(FakeSearcher(failing=("team",)))
    report = ResearchReport.model_validate(result["report"])

    assert "Jane Roe" not in [p.name for p in report.people]
    assert [e["node"] for e in result["errors"]] == ["research_team"]


def test_the_run_raises_when_every_lookup_fails():
    with pytest.raises(LLMError, match="every web lookup failed"):
        run(FakeSearcher(failing=("company", "team", "recruiting")))


def test_research_thread_is_the_analysis_id_with_a_suffix():
    assert research_thread("a1") == "a1:research"
