"""Render the rebuilt CV to DOCX and PDF, and check that the PDF reads back."""

from backedcv.rendering.docx_writer import render_docx
from backedcv.rendering.layout import LAYOUTS, STANDARD, Layout
from backedcv.rendering.pdf_writer import FittedPdf, fit_pdf, page_count, render_pdf
from backedcv.rendering.roundtrip import roundtrip_check

PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

__all__ = [
    "DOCX_TYPE",
    "LAYOUTS",
    "PDF_TYPE",
    "STANDARD",
    "FittedPdf",
    "Layout",
    "fit_pdf",
    "page_count",
    "render_docx",
    "render_pdf",
    "roundtrip_check",
]
