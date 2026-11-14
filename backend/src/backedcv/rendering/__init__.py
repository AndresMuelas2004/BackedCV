"""Render the rebuilt CV to DOCX and PDF, in the look of the uploaded file or in the plain
template, and check that the PDF reads back."""

from backedcv.rendering.docx_writer import render_docx
from backedcv.rendering.layout import LAYOUTS, STANDARD, Layout
from backedcv.rendering.mirror import Mirror, mirror_of
from backedcv.rendering.mirror_docx import render_mirror_docx
from backedcv.rendering.mirror_writer import FittedMirror, fit_mirror_pdf, render_mirror_pdf
from backedcv.rendering.pdf_writer import FittedPdf, fit_pdf, page_count, render_pdf
from backedcv.rendering.roundtrip import roundtrip_check, roundtrip_lines

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

__all__ = [
    "DOCX_TYPE",
    "LAYOUTS",
    "PDF_TYPE",
    "STANDARD",
    "FittedMirror",
    "FittedPdf",
    "Layout",
    "Mirror",
    "fit_mirror_pdf",
    "fit_pdf",
    "mirror_of",
    "page_count",
    "render_docx",
    "render_mirror_docx",
    "render_mirror_pdf",
    "render_pdf",
    "roundtrip_check",
    "roundtrip_lines",
]
