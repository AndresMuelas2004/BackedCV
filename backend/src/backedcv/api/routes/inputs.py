"""Inputs given after the report (answers, toggles): the score is recomputed, no model call."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backedcv.api.errors import ApiError, analysis_not_found
from backedcv.api.projection import project, waiting_at_report
from backedcv.domain.models import CandidateFacts, JobPosting
from backedcv.domain.statements import can_state
from backedcv.graph.builder import run_config
from backedcv.graph.recompute import recompute

router = APIRouter(tags=["analyses"])


class InputsUpdate(BaseModel):
    """Omitted fields keep their current value; a list that is sent replaces the old list."""

    facts: CandidateFacts | None = (
        None  # answers (requirement or barrier IDs, yes or no) and the candidate's statements
    )
    excluded_ids: list[str] | None = Field(default=None, max_length=200)  # marked as not relevant
    included_flagged_ids: list[str] | None = Field(default=None, max_length=200)  # counted again


@router.patch("/analyses/{analysis_id}/inputs")
async def update_inputs(request: Request, analysis_id: str, update: InputsUpdate) -> dict:
    graph, locks = request.app.state.graph, request.app.state.locks
    config = run_config(analysis_id)
    locks.acquire(analysis_id)
    async with locks.held(analysis_id):
        snapshot = await graph.aget_state(config)
        if not snapshot.values:
            raise analysis_not_found()
        if not waiting_at_report(snapshot):
            raise ApiError(409, "not_paused", "Inputs can only change once the report is ready.")
        changes = _merge(snapshot.values, update)
        values = {**changes, **recompute({**snapshot.values, **changes})}
        # Written as if the score node had just run; the next node is still the optimize pause.
        await graph.aupdate_state(config, values, as_node="score_and_verdict")
    return project(analysis_id, await graph.aget_state(config))


def _merge(state: dict, update: InputsUpdate) -> dict:
    """The input values after the update. Requirement IDs the posting does not have, and
    statements about requirements that cannot take one, are refused before any write."""
    requirements = {req.id: req for req in JobPosting.model_validate(state["job"]).requirements}
    sent = [*(update.excluded_ids or []), *(update.included_flagged_ids or [])]
    unknown = sorted(set(sent) - set(requirements))
    if unknown:
        raise ApiError(
            422, "inputs_invalid", "Some requirements are not in this posting.", ", ".join(unknown)
        )
    told = update.facts.statements if update.facts is not None else {}
    closed = sorted(
        rid for rid in told if rid not in requirements or not can_state(requirements[rid])
    )
    if closed:
        raise ApiError(
            422, "inputs_invalid", "Some requirements cannot take a statement.", ", ".join(closed)
        )
    return {
        "facts": _merge_facts(state.get("facts"), update.facts).model_dump(),
        "excluded_ids": _sent_or_current(update.excluded_ids, state.get("excluded_ids")),
        "included_flagged_ids": _sent_or_current(
            update.included_flagged_ids, state.get("included_flagged_ids")
        ),
    }


def _merge_facts(current: dict | None, sent: CandidateFacts | None) -> CandidateFacts:
    """Answers that are sent are added to the ones already given, so one answer keeps the rest.
    Any other field that is sent replaces its old value."""
    old = CandidateFacts.model_validate(current or {})
    if sent is None:
        return old
    changes = sent.model_dump(exclude_unset=True)
    answers = {**old.answers, **changes.pop("answers", {})}
    return CandidateFacts.model_validate({**old.model_dump(), **changes, "answers": answers})


def _sent_or_current(sent: list[str] | None, current: list[str] | None) -> list[str]:
    return list(current or []) if sent is None else sent
