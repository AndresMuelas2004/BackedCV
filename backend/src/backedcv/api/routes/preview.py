"""Keyword coverage with some suggestions accepted. No model is called and nothing is saved."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backedcv.api.errors import ApiError
from backedcv.api.projection import waiting_at_review
from backedcv.domain.coverage import coverage_after, shown_lines
from backedcv.domain.document_diff import apply_suggestions, document_from_cv
from backedcv.domain.keywords import keyword_present
from backedcv.domain.models import (
    CVDocument,
    JobPosting,
    ParsedCV,
    Suggestion,
)
from backedcv.graph.builder import run_config
from backedcv.graph.recompute import assessments_of, flagged_of

router = APIRouter(tags=["analyses"])


class CoveragePreview(BaseModel):
    accepted: list[str] = Field(
        default_factory=list, max_length=100
    )  # suggestion IDs, e.g. ["S01", "S03"]


@router.post("/analyses/{analysis_id}/coverage-preview")
async def coverage_preview(request: Request, analysis_id: str, body: CoveragePreview) -> dict:
    """Keyword coverage now and with the accepted suggestions. Only verified suggestions count:
    an accepted one that failed verification adds nothing."""
    snapshot = await request.app.state.graph.aget_state(run_config(analysis_id))
    values: dict[str, Any] = snapshot.values
    if not values:
        raise ApiError(404, "not_found", "This analysis does not exist or has expired.")
    if not waiting_at_review(snapshot):
        raise ApiError(
            409,
            "wrong_stage",
            "Coverage can only be previewed while the suggestions wait for review.",
        )

    suggestions = [Suggestion.model_validate(row) for row in values.get("suggestions") or []]
    unknown = sorted(set(body.accepted) - {s.id for s in suggestions})
    if unknown:
        raise ApiError(
            422,
            "decisions_invalid",
            "Some suggestions are not part of this analysis.",
            ", ".join(unknown),
        )

    cv = ParsedCV.model_validate(values["cv"])
    job = JobPosting.model_validate(values.get("job") or {})
    assessments = assessments_of(values)
    flagged = flagged_of(values)
    excluded = values.get("excluded_ids") or []
    included = values.get("included_flagged_ids") or []

    def coverage(doc: CVDocument) -> float | None:
        return coverage_after(
            job.requirements,
            assessments,
            doc,
            excluded_ids=excluded,
            flagged=flagged,
            included_flagged_ids=included,
        )

    now = document_from_cv(cv)
    after = apply_suggestions(now, cv, suggestions, body.accepted)
    # The same lines coverage_after counts, so the gained IDs agree with the coverage numbers.
    lines_now, lines_after = shown_lines(now), shown_lines(after)
    return {
        "coverage": coverage(after),
        "coverage_now": coverage(now),
        "gained_requirement_ids": [
            req.id
            for req in job.requirements
            if keyword_present(req, lines_after) and not keyword_present(req, lines_now)
        ],
    }
