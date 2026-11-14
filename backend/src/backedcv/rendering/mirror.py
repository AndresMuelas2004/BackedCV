"""The built CV in the look of the uploaded file, when that look was read: its rows and its page."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backedcv.domain.mirror import mirror_rows
from backedcv.domain.models import CVDocument, LineFormat, PageLayout, ParsedCV, Suggestion


@dataclass(frozen=True)
class Mirror:
    rows: list[LineFormat]
    page: PageLayout
    title: str


def mirror_of(values: Mapping[str, Any], doc: CVDocument) -> Mirror | None:
    """The rows and the page of the built CV in the uploaded file's look, read from the analysis
    state. None when the file's look was not read (pasted text, a Word file)."""
    layout = (values.get("cv_meta") or {}).get("layout")
    cv = values.get("cv")
    if not layout or not cv:
        return None
    suggestions = [Suggestion.model_validate(row) for row in values.get("suggestions") or []]
    # The rows keep the CV's own order unless the user asked the agent for a new one.
    rows = mirror_rows(
        ParsedCV.model_validate(cv), doc, suggestions, keep_order=values.get("built_by") != "agent"
    )
    if rows is None:
        return None
    return Mirror(rows=rows, page=PageLayout.model_validate(layout), title=doc.contact.name or "CV")
