"""PDF CVs: words with positions and fonts, grouped into lines in reading order."""

import io
from dataclasses import dataclass
from statistics import median

import pdfplumber

from backedcv.domain.models import PageLayout
from backedcv.ingestion.columns import page_order
from backedcv.ingestion.errors import IngestionError
from backedcv.ingestion.lines import (
    BULLET_GLYPHS,
    Fragment,
    RawLine,
    group_fragments,
    merge_fragments,
)
from backedcv.ingestion.pdf_format import (
    PageMarks,
    Shape,
    attach_rules,
    line_shape,
    merge_shapes,
    page_layout,
    page_marks,
)

_BOLD_HINTS = ("bold", "black", "heavy", "semibold", "demi")
_BIGGER = 1.08  # a line this many times the page's running text size is a heading


@dataclass
class PdfRead:
    rows: list[RawLine]
    multi_column: bool  # at least one page was read as two columns
    layout: PageLayout


def read_pdf(data: bytes, max_pages: int) -> PdfRead:
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # pdfminer raises several unrelated types
        raise IngestionError("cv_unreadable", "This PDF could not be opened.", str(exc)) from exc

    with pdf:
        if len(pdf.pages) > max_pages:
            raise IngestionError(
                "cv_too_many_pages",
                f"This CV has {len(pdf.pages)} pages; the limit is {max_pages}.",
            )
        rows: list[RawLine] = []
        multi_column = False
        pages_data: list[tuple[float, float, list[Shape], list[dict], float]] = []
        for page_number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(
                keep_blank_chars=False,
                use_text_flow=False,
                extra_attrs=["fontname", "size"],
                return_chars=True,
            )
            order = page_order(words, float(page.width))
            multi_column = multi_column or order.multi_column
            body = _body_size(words)
            marks = page_marks(page)
            page_shapes: list[Shape] = []
            for block in order.blocks:
                fragments = _group_lines(
                    block,
                    page_number,
                    body,
                    marks,
                    float(page.height),
                    float(page.width),
                    one_column=not order.multi_column,
                )
                page_shapes.extend(f.shape for f in fragments if f.shape is not None)
                rows.extend(_rows(fragments))
            stroke_right = max((float(s["x1"]) for s in marks.strokes), default=0.0)
            pages_data.append(
                (float(page.width), float(page.height), page_shapes, words, stroke_right)
            )

    if not rows:
        raise IngestionError(
            "cv_image_only",
            "No text could be read from this PDF.",
            "It looks like a scanned image. Paste the CV text instead.",
        )
    layout = page_layout(pages_data, multi_column)
    pitches = [r.fmt.pitch for r in rows if r.fmt is not None and r.fmt.pitch is not None]
    layout.pitch = round(median(pitches), 2) if pitches else None
    for row in rows:
        if row.fmt is None:
            continue
        # The running text colour is the default, so the spans need not repeat it.
        for span in [*row.fmt.spans, *row.fmt.tail]:
            if span.color == layout.color:
                span.color = None
    return PdfRead(rows=rows, multi_column=multi_column, layout=layout)


def _body_size(words: list[dict]) -> float:
    """Median font size of the page: the size of its running text."""
    sizes = [float(w["size"]) for w in words if w.get("size")]
    return median(sizes) if sizes else 0.0


def _rows(fragments: list[Fragment]) -> list[RawLine]:
    """The logical lines of one column block, each with its look and its distance from the line
    above."""
    rows: list[RawLine] = []
    previous: float | None = None  # baseline of the last physical line before this one
    for group in group_fragments(fragments):
        row = merge_fragments(group)
        shapes = [f.shape for f in group if f.shape is not None]
        texts = [f.text for f in group if f.shape is not None]
        row.fmt = merge_shapes(shapes, texts)
        if previous is not None:
            gap = shapes[0].baseline - previous
            if gap > 0:
                row.fmt.gap_before = round(gap, 2)
        previous = shapes[-1].baseline
        rows.append(row)
    return rows


def _group_lines(
    words: list[dict],
    page_number: int,
    body: float,
    marks: PageMarks,
    page_height: float,
    page_width: float,
    *,
    one_column: bool,
) -> list[Fragment]:
    """Words whose vertical positions overlap form one physical line; lines run top to bottom."""
    left = min(float(w["x0"]) for w in words)
    right = max(float(w["x1"]) for w in words)
    if one_column:
        # Side margins are nearly always equal, and a rule across the page shows the text area;
        # the ink alone would make short lines look indented or right-aligned.
        stroke_right = max((float(s["x1"]) for s in marks.strokes), default=0.0)
        right = max(right, page_width - left, stroke_right)
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    groups: list[list[dict]] = []
    for word in words:
        if groups:
            last = groups[-1]
            ref_top = median(w["top"] for w in last)
            tolerance = max(2.0, 0.4 * float(word.get("size") or 10))
            if abs(word["top"] - ref_top) <= tolerance:
                last.append(word)
                continue
        groups.append([word])

    fragments: list[Fragment] = []
    for group in groups:
        group.sort(key=lambda w: w["x0"])
        shape = line_shape(group, left, right, marks, page_height)
        fonts = [str(w.get("fontname", "")).lower() for w in group]
        bold = all(any(h in f for h in _BOLD_HINTS) for f in fonts)
        size = round(median(float(w.get("size") or 0) for w in group), 1)
        fragments.append(
            Fragment(
                text=shape.text,
                page=page_number,
                x0=min(w["x0"] for w in group),
                x1=max(w["x1"] for w in group),
                top=min(w["top"] for w in group),
                bottom=max(w["bottom"] for w in group),
                # With a bullet, the text starts where the shape says, after the marker.
                text_x0=left + shape.indent if shape.bullet is not None else _text_x0(group),
                size=size,
                bold=bold,
                heading=bold or (body > 0 and size >= body * _BIGGER),
                shape=shape,
            )
        )
    attach_rules([f.shape for f in fragments if f.shape is not None], marks, left, right)
    return fragments


def _text_x0(group: list[dict]) -> float:
    """Left edge of the first letter or digit, so a bullet glyph in front of it is skipped."""
    chars = sorted((c for w in group for c in w.get("chars", [])), key=lambda c: c["x0"])
    for char in chars:
        if char["text"].strip() and char["text"] not in BULLET_GLYPHS:
            return float(char["x0"])
    return float(min(w["x0"] for w in group))
