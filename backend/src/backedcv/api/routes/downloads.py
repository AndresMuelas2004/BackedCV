"""Downloads of the built CV, and deleting an analysis with its checkpoints."""

import asyncio

from fastapi import APIRouter, Request, Response

from backedcv.api.errors import ApiError, analysis_not_found
from backedcv.domain.models import CVDocument
from backedcv.graph.builder import run_config
from backedcv.rendering import DOCX_TYPE, PDF_TYPE, render_docx, render_pdf

router = APIRouter(tags=["analyses"])


@router.get("/analyses/{analysis_id}/cv.docx")
async def download_docx(request: Request, analysis_id: str) -> Response:
    doc = await _built_document(request, analysis_id)
    return _attachment(render_docx(doc), DOCX_TYPE, "cv-backedcv.docx")


@router.get("/analyses/{analysis_id}/cv.pdf")
async def download_pdf(request: Request, analysis_id: str) -> Response:
    doc = await _built_document(request, analysis_id)
    # Typst takes a moment: it runs in a worker thread so other requests are not held up.
    return _attachment(await asyncio.to_thread(render_pdf, doc), PDF_TYPE, "cv-backedcv.pdf")


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


def _attachment(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
