"""The candidate says where they did what the CV leaves out; a checked line is written from it."""

import json

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from backedcv.llm.drafts_optimize import AdditionDraft
from backedcv.main import create_app
from tests.fakes import CV_TEXT, JOB_TEXT
from tests.fakes_optimize import FakeOptimizeLLM

# In tests/fakes, R06 is "dbt" (a preferred skill the CV does not show), R05 is the work
# authorization knockout and E01 is the job "Data Engineer, Acme Corp".
TOLD = "At Acme Corp I built our dbt models for the finance team."
LINE = "Built dbt models for the finance team"


def _addition(after: str = LINE, kind: str = "add_line", reason: str = "") -> AdditionDraft:
    entry = "E01" if kind == "add_line" else None
    return AdditionDraft(statement_id="U06", kind=kind, entry_id=entry, after=after, reason=reason)


@pytest.fixture
def start():
    """Starts an app whose model writes the given lines from the candidate's statements."""
    clients = []

    def _start(*additions: AdditionDraft) -> tuple[TestClient, FakeOptimizeLLM]:
        llm = FakeOptimizeLLM(suggestions=[], additions=list(additions))
        client = TestClient(create_app(llm=llm, checkpointer=InMemorySaver()))
        client.__enter__()
        clients.append(client)
        return client, llm

    yield _start
    for client in clients:
        client.__exit__(None, None, None)


def _last(response) -> dict:
    """The data of the last event of a stream."""
    assert response.status_code == 200, response.text
    data = {}
    for block in response.text.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line and line[0] != ":"
        )
        if "event" in fields:
            data = json.loads(fields["data"])
    return data


def _analysis(client: TestClient) -> str:
    response = client.post("/api/analyses", data={"cv_text": CV_TEXT, "job_text": JOB_TEXT})
    return _last(response)["analysis_id"]


def _tell(client: TestClient, analysis_id: str, statements: dict[str, str]):
    body = {"facts": {"statements": statements}}
    return client.patch(f"/api/analyses/{analysis_id}/inputs", json=body)


def _optimized(client: TestClient, analysis_id: str) -> dict:
    return _last(client.post(f"/api/analyses/{analysis_id}/optimize"))


def test_a_statement_becomes_a_checked_line_under_its_job(start):
    client, llm = start(_addition())
    analysis_id = _analysis(client)

    saved = _tell(client, analysis_id, {"R06": TOLD})
    review = _optimized(client, analysis_id)

    assert saved.json()["facts"]["statements"] == {"R06": TOLD}
    [line] = review["suggestions"]
    assert (line["kind"], line["source"], line["target"]) == ("add_line", "candidate", "E01")
    assert (line["after"], line["cited_refs"], line["requirement_ids"]) == (LINE, ["U06"], ["R06"])
    assert line["verification"]["status"] == "verified"
    assert review["skipped_statements"] == []
    # The model that writes the line reads the jobs of the CV and the candidate's own words.
    written = next(
        data for _, data in llm.inputs if "<statements>" in data and "<cv_entries>" in data
    )
    assert "E01 | job | Data Engineer | Acme Corp" in written
    assert f'U06 | requirement: dbt | terms: "dbt" | says: {TOLD}' in written


def test_the_line_reaches_the_new_cv_and_raises_fit(start):
    client, _ = start(_addition())
    analysis_id = _analysis(client)
    _tell(client, analysis_id, {"R06": TOLD})
    _optimized(client, analysis_id)

    built = _last(client.post(f"/api/analyses/{analysis_id}/build", json={"accepted": ["S01"]}))

    job = next(
        item
        for section in built["document"]["sections"]
        for item in section["items"]
        if item["id"] == "E01"
    )
    assert job["lines"][-1] == {"text": LINE, "origin": "S01", "kind": "bullet"}
    report = built["build_report"]
    assert report["validation_errors"] == []
    assert report["fit_after"] > report["fit"]


def test_a_number_the_candidate_did_not_give_stops_at_the_guards(start):
    client, llm = start(_addition("Built 12 dbt models for the finance team"))
    analysis_id = _analysis(client)
    _tell(client, analysis_id, {"R06": TOLD})

    [line] = _optimized(client, analysis_id)["suggestions"]

    assert line["verification"]["status"] == "unsupported"
    assert "12" in line["verification"]["reason"]
    assert "verify_batch" not in llm.calls  # a failed guard never reaches the verifier


def test_nothing_is_written_when_the_candidate_has_not_done_it(start):
    reason = "You say you have not used dbt, so nothing is added."
    client, _ = start(_addition("", kind="none", reason=reason))
    analysis_id = _analysis(client)
    _tell(client, analysis_id, {"R06": "Never used it, but I learn fast."})

    review = _optimized(client, analysis_id)

    assert review["suggestions"] == []
    assert review["skipped_statements"] == [{"requirement_id": "R06", "reason": reason}]


def test_only_skills_of_the_posting_can_take_a_statement(start):
    client, _ = start()
    analysis_id = _analysis(client)

    gate = _tell(client, analysis_id, {"R05": "I have a US work permit."})
    unknown = _tell(client, analysis_id, {"R99": TOLD})
    too_long = _tell(client, analysis_id, {"R06": "x" * 501})

    assert (gate.status_code, gate.json()["code"]) == (422, "inputs_invalid")
    assert (unknown.status_code, unknown.json()["code"]) == (422, "inputs_invalid")
    assert (too_long.status_code, too_long.json()["code"]) == (422, "invalid_request")


def test_an_edited_line_is_checked_against_the_candidates_words_again(start):
    client, _ = start(_addition())
    analysis_id = _analysis(client)
    _tell(client, analysis_id, {"R06": TOLD})
    _optimized(client, analysis_id)
    url = f"/api/analyses/{analysis_id}/suggestions/S01/verify"

    stretched = client.post(url, json={"after": "Built 12 dbt models for the finance team"}).json()
    faithful = client.post(url, json={"after": "Built the dbt models of the finance team"}).json()

    assert stretched["suggestions"][0]["verification"]["status"] == "unsupported"
    assert faithful["suggestions"][0]["verification"]["status"] == "verified"
    assert faithful["suggestions"][0]["source"] == "candidate"


def test_sending_the_statements_again_replaces_them(start):
    client, _ = start()
    analysis_id = _analysis(client)
    _tell(client, analysis_id, {"R06": TOLD})

    cleared = _tell(client, analysis_id, {})

    assert cleared.json()["facts"]["statements"] == {}


def test_a_line_that_does_not_name_the_skill_is_not_added(start):
    client, _ = start(_addition("Built models for the finance team"))
    analysis_id = _analysis(client)
    _tell(client, analysis_id, {"R06": TOLD})

    review = _optimized(client, analysis_id)

    assert review["suggestions"] == []
    assert review["skipped_statements"] == [
        {"requirement_id": "R06", "reason": "Your words do not name dbt, so nothing was added."}
    ]
