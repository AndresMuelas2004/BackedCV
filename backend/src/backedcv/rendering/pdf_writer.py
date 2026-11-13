"""Render the rebuilt CV to PDF with Typst, using the bundled ATS-safe template."""

import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber
import typst

from backedcv.domain.models import CVDocument
from backedcv.rendering.layout import LAYOUTS, STANDARD, Layout

TEMPLATE = Path(__file__).parent / "templates" / "cv.typ"


@dataclass(frozen=True)
class FittedPdf:
    pdf: bytes
    pages: int
    layout: Layout
    fits: bool  # False: even the tightest layout needs more pages than asked


def render_pdf(doc: CVDocument, layout: Layout = STANDARD) -> bytes:
    """Pass the document and the layout to the template as JSON in sys.inputs."""
    payload = json.dumps(doc.model_dump(mode="json"), ensure_ascii=False)
    return typst.compile(
        TEMPLATE,
        format="pdf",
        ignore_system_fonts=True,  # embedded fonts only, so the PDF looks the same on every machine
        sys_inputs={"data": payload, "layout": json.dumps(asdict(layout))},
    )


def page_count(pdf: bytes) -> int:
    with pdfplumber.open(io.BytesIO(pdf)) as opened:
        return len(opened.pages)


def fit_pdf(doc: CVDocument, max_pages: int | None = None) -> FittedPdf:
    """The CV in the first layout, from the standard one to the tightest, that takes at most
    `max_pages` pages. Nothing is ever cut: when none fits, the tightest layout comes back with
    `fits` False. Without a limit, the standard layout."""
    if max_pages is None:
        pdf = render_pdf(doc)
        return FittedPdf(pdf, page_count(pdf), STANDARD, True)
    for layout in LAYOUTS:
        pdf = render_pdf(doc, layout)
        pages = page_count(pdf)
        if pages <= max_pages:
            return FittedPdf(pdf, pages, layout, True)
    return FittedPdf(pdf, pages, layout, False)
