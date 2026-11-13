"""Build nodes: apply the accepted suggestions, order the result, run the final checks."""

import asyncio
import logging
from collections.abc import Callable

from langchain_core.language_models import BaseChatModel

from backedcv.agents.cv_builder import Workspace, run_order_agent
from backedcv.domain.coverage import coverage_after
from backedcv.domain.document_diff import (
    apply_suggestions,
    diff_document,
    document_from_cv,
    standard_order,
    validate_document,
)
from backedcv.domain.models import (
    BuildReport,
    CVDocument,
    JobPosting,
    ParsedCV,
    RequirementAssessment,
    ReviewDecisions,
    Suggestion,
)
from backedcv.domain.scoring import compute_score
from backedcv.graph.nodes import _error, _progress
from backedcv.graph.recompute import assessments_of, flagged_of
from backedcv.graph.state import AnalysisState
from backedcv.rendering import render_pdf, roundtrip_check

log = logging.getLogger(__name__)


def make_build_nodes(order_model: BaseChatModel | None = None) -> dict[str, Callable]:
    """The build_cv and final_checks nodes. Without an order model, the standard section order
    is used."""

    async def build_cv(state: AnalysisState) -> dict:
        _progress("build", "started")
        cv = ParsedCV.model_validate(state["cv"])
        applied = _applied(state)
        accepted = {s.id for s in applied}
        doc = apply_suggestions(document_from_cv(cv), cv, applied, accepted)
        built_by, usage, errors = "fallback", [], []
        if order_model is not None:
            ws = Workspace(document=doc, cv=cv, applied=applied, accepted_ids=accepted)
            doc, built_by = await run_order_agent(ws, _job_summary(state), order_model)
            usage = ws.usage
            errors = [_error("build_cv", ws.error)] if ws.error is not None else []
        else:
            doc = standard_order(doc)
        _progress("build", "done", built_by=built_by)
        return {
            "document": doc.model_dump(),
            "built_by": built_by,
            "usage": usage,
            "errors": errors,
        }

    async def final_checks(state: AnalysisState) -> dict:
        _progress("checks", "started")
        cv = ParsedCV.model_validate(state["cv"])
        doc = CVDocument.model_validate(state["document"])
        applied = _applied(state)
        accepted = {s.id for s in applied}
        score = state.get("score") or {}
        job = JobPosting.model_validate(state.get("job") or {})
        assessments = assessments_of(state)
        flagged = flagged_of(state)
        gained = {rid for s in applied if s.source == "candidate" for rid in s.requirement_ids}
        # Typst and the PDF read-back take a moment: a worker thread keeps other requests moving.
        roundtrip_ok, issues = await asyncio.to_thread(_roundtrip, doc)
        report = BuildReport(
            diff=diff_document(cv, doc, applied),
            coverage_before=score.get("coverage"),
            coverage_after=coverage_after(
                job.requirements,
                assessments,
                doc,
                excluded_ids=state.get("excluded_ids") or [],
                flagged=flagged,
                included_flagged_ids=state.get("included_flagged_ids") or [],
            ),
            fit=score.get("fit"),
            fit_after=_fit_with(job, assessments, gained, state, flagged) if gained else None,
            roundtrip_ok=roundtrip_ok,
            roundtrip_issues=issues,
            built_by=state.get("built_by") or "fallback",
            validation_errors=validate_document(doc, cv, applied, accepted),
        )
        _progress("checks", "done", roundtrip_ok=roundtrip_ok)
        return {"build_report": report.model_dump()}

    return {"build_cv": build_cv, "final_checks": final_checks}


def _applied(state: AnalysisState) -> list[Suggestion]:
    """The suggestions the user accepted and the verifier passed, in their stored order."""
    accepted = set(ReviewDecisions.model_validate(state.get("decisions") or {}).accepted)
    suggestions = [Suggestion.model_validate(row) for row in state.get("suggestions") or []]
    return [s for s in suggestions if s.id in accepted and s.verification.status == "verified"]


def _job_summary(state: AnalysisState) -> str:
    """The posting's title and its requirements, one per line, for the order agent."""
    job = JobPosting.model_validate(state.get("job") or {})
    rows = [f"- {req.label} ({req.importance})" for req in job.requirements]
    return "\n".join([f"Title: {job.title or 'unknown'}", *rows])


def _fit_with(
    job: JobPosting,
    assessments: dict[str, RequirementAssessment],
    gained: set[str],
    state: AnalysisState,
    flagged: dict[str, str],
) -> float | None:
    """Fit of the new CV: the requirements the candidate's own lines were written for now count
    as met, because the CV shows them."""
    shown = {
        rid: a.model_copy(update={"status": "met"}) if rid in gained else a
        for rid, a in assessments.items()
    }
    return compute_score(
        job.requirements,
        shown,
        excluded_ids=state.get("excluded_ids") or [],
        flagged=flagged,
        included_flagged_ids=state.get("included_flagged_ids") or [],
    ).fit


def _roundtrip(doc: CVDocument) -> tuple[bool, list[str]]:
    """Render the CV and read the PDF back. A failed render is a failed check, never an error."""
    try:
        return roundtrip_check(render_pdf(doc), doc)
    except Exception as exc:  # the build report must still be written
        log.warning("CV render failed: %s", exc)
        return False, [f"The PDF could not be rendered: {type(exc).__name__}: {exc}"[:300]]
