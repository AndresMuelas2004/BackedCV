"""Downloads of the built CV, and deleting an analysis with its checkpoints."""

import asyncio
import re
import unicodedata
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response

from backedcv.api.errors import ApiError, analysis_not_found
from backedcv.domain.models import CVDocument
from backedcv.graph.builder import run_config
from backedcv.graph.research import research_thread
from backedcv.rendering import (
    DOCX_TYPE,
    PDF_TYPE,
    STANDARD,
    Mirror,
    fit_mirror_pdf,
    fit_pdf,
    mirror_of,
    render_docx,
    render_mirror_docx,
)

router = APIRouter(tags=["analyses"])

# A page limit for the built CV: 1 to 3 pages, or none.
MaxPages = Annotated[int | None, Query(ge=1, le=3)]
# The format of the built CV: "original" is the look of the uploaded file, "standard" the plain
# template. Without it, the uploaded file's look is used when it was read.
Style = Annotated[Literal["original", "standard"] | None, Query()]


@router.get("/analyses/{analysis_id}/cv.docx")
async def download_docx(
    request: Request, analysis_id: str, max_pages: MaxPages = None, style: Style = None
) -> Response:
    doc, mirror = await _built(request, analysis_id)
    shown = mirror if style != "standard" else None
    if shown is not None:
        # The DOCX takes the text size the PDF needs to fit the limit.
        fitted = await asyncio.to_thread(
            fit_mirror_pdf, shown.rows, shown.page, shown.title, max_pages
        )
        content = render_mirror_docx(shown.rows, shown.page, shown.title, fitted.scale)
    else:
        # The DOCX takes the text size and margins the PDF needs to fit the limit.
        layout = STANDARD
        if max_pages:
            layout = (await asyncio.to_thread(fit_pdf, doc, max_pages)).layout
        content = render_docx(doc, layout)
    return _attachment(content, DOCX_TYPE, download_name(doc, "docx"))


@router.get("/analyses/{analysis_id}/cv.pdf")
async def download_pdf(
    request: Request, analysis_id: str, max_pages: MaxPages = None, style: Style = None
) -> Response:
    doc, mirror = await _built(request, analysis_id)
    shown = mirror if style != "standard" else None
    # Typst takes a moment: it runs in a worker thread so other requests are not held up.
    if shown is not None:
        fitted = await asyncio.to_thread(
            fit_mirror_pdf, shown.rows, shown.page, shown.title, max_pages
        )
        return _attachment(fitted.pdf, PDF_TYPE, download_name(doc, "pdf"))
    fitted = await asyncio.to_thread(fit_pdf, doc, max_pages)
    return _attachment(fitted.pdf, PDF_TYPE, download_name(doc, "pdf"))


@router.get("/analyses/{analysis_id}/cv-layout")
async def cv_layout(
    request: Request, analysis_id: str, max_pages: MaxPages = None, style: Style = None
) -> dict:
    """How many pages the built CV takes, and whether it fits a page limit."""
    doc, mirror = await _built(request, analysis_id)
    shown = mirror if style != "standard" else None
    if shown is not None:
        fitted = await asyncio.to_thread(
            fit_mirror_pdf, shown.rows, shown.page, shown.title, max_pages
        )
        return {
            "pages": fitted.pages,
            "max_pages": max_pages,
            "fits": fitted.fits,
            "font_size": round(shown.page.size * fitted.scale, 1),
            "standard_font_size": shown.page.size,
            "style": "original",
            **_formats(mirror),
        }
    fitted = await asyncio.to_thread(fit_pdf, doc, max_pages)
    return {
        "pages": fitted.pages,
        "max_pages": max_pages,
        "fits": fitted.fits,
        "font_size": fitted.layout.font_size,
        "standard_font_size": STANDARD.font_size,
        "style": "standard",
        **_formats(mirror),
    }


@router.delete("/analyses/{analysis_id}", status_code=204)
async def delete_analysis(request: Request, analysis_id: str) -> Response:
    graph, locks = request.app.state.graph, request.app.state.locks
    locks.acquire(analysis_id)  # 409 while a run holds the analysis
    async with locks.held(analysis_id):
        research = research_thread(analysis_id)
        locks.acquire(research)  # 409 while its deeper analysis runs
        async with locks.held(research):
            snapshot = await graph.aget_state(run_config(analysis_id))
            if not snapshot.values:
                raise analysis_not_found()
            await request.app.state.checkpointer.adelete_thread(analysis_id)
            await request.app.state.checkpointer.adelete_thread(research)
            request.app.state.ledger.remove(analysis_id)
    return Response(status_code=204)


async def _built(request: Request, analysis_id: str) -> tuple[CVDocument, Mirror | None]:
    """The built document, and its rows in the uploaded file's look when that look was read."""
    snapshot = await request.app.state.graph.aget_state(run_config(analysis_id))
    if not snapshot.values:
        raise analysis_not_found()
    document = snapshot.values.get("document")
    if document is None:
        raise ApiError(409, "not_built", "The CV has not been built yet.")
    doc = CVDocument.model_validate(document)
    return doc, await asyncio.to_thread(mirror_of, snapshot.values, doc)


def _formats(mirror: Mirror | None) -> dict:
    """The formats this CV can be built in, and what is known of the uploaded file's pages."""
    return {
        "styles": ["original", "standard"] if mirror is not None else ["standard"],
        "original_pages": mirror.page.pages if mirror is not None else None,
        "columns": mirror.page.columns if mirror is not None else 1,
    }


def download_name(doc: CVDocument, extension: str) -> str:
    """ "Jane-Doe-CV.pdf": the candidate's name in plain ASCII, or "CV.pdf" without a name."""
    name = unicodedata.normalize("NFKD", doc.contact.name or "")
    words = re.findall(r"[A-Za-z0-9]+", name.encode("ascii", "ignore").decode())[:6]
    return "-".join([*words, "CV"]) + f".{extension}"


def _attachment(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
