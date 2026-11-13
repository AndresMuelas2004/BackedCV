"""Downloads of the built CV, and deleting an analysis with its checkpoints."""

import asyncio
import re
import unicodedata
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from backedcv.api.errors import ApiError, analysis_not_found
from backedcv.domain.models import CVDocument
from backedcv.graph.builder import run_config
from backedcv.rendering import DOCX_TYPE, PDF_TYPE, STANDARD, fit_pdf, render_docx

router = APIRouter(tags=["analyses"])

# A page limit for the built CV: 1 to 3 pages, or none.
MaxPages = Annotated[int | None, Query(ge=1, le=3)]


@router.get("/analyses/{analysis_id}/cv.docx")
async def download_docx(request: Request, analysis_id: str, max_pages: MaxPages = None) -> Response:
    doc = await _built_document(request, analysis_id)
    # The DOCX takes the text size and margins the PDF needs to fit the limit.
    layout = (await asyncio.to_thread(fit_pdf, doc, max_pages)).layout if max_pages else STANDARD
    return _attachment(render_docx(doc, layout), DOCX_TYPE, download_name(doc, "docx"))


@router.get("/analyses/{analysis_id}/cv.pdf")
async def download_pdf(request: Request, analysis_id: str, max_pages: MaxPages = None) -> Response:
    doc = await _built_document(request, analysis_id)
    # Typst takes a moment: it runs in a worker thread so other requests are not held up.
    fitted = await asyncio.to_thread(fit_pdf, doc, max_pages)
    return _attachment(fitted.pdf, PDF_TYPE, download_name(doc, "pdf"))


@router.get("/analyses/{analysis_id}/cv-layout")
async def cv_layout(request: Request, analysis_id: str, max_pages: MaxPages = None) -> dict:
    """How many pages the built CV takes, and whether it fits a page limit."""
    doc = await _built_document(request, analysis_id)
    fitted = await asyncio.to_thread(fit_pdf, doc, max_pages)
    return {
        "pages": fitted.pages,
        "max_pages": max_pages,
        "fits": fitted.fits,
        "font_size": fitted.layout.font_size,
        "standard_font_size": STANDARD.font_size,
    }


@router.delete("/analyses/{analysis_id}", status_code=204)
async def delete_analysis(request: Request, analysis_id: str) -> Response:
    graph, locks = request.app.state.graph, request.app.state.locks
    locks.acquire(analysis_id)  # 409 while a run holds the analysis
    async with locks.held(analysis_id):
        snapshot = await graph.aget_state(run_config(analysis_id))
        if not snapshot.values:
            raise analysis_not_found()
        await request.app.state.checkpointer.adelete_thread(analysis_id)
        request.app.state.ledger.remove(analysis_id)
    return Response(status_code=204)


async def _built_document(request: Request, analysis_id: str) -> CVDocument:
    snapshot = await request.app.state.graph.aget_state(run_config(analysis_id))
    if not snapshot.values:
        raise analysis_not_found()
    document = snapshot.values.get("document")
    if document is None:
        raise ApiError(409, "not_built", "The CV has not been built yet.")
    return CVDocument.model_validate(document)


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
