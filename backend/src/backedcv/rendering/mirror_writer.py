"""Render the built CV in the look of the uploaded file: Typst sets the rows one by one from the
format read from that file (domain/mirror.py), in the bundled twin of its font."""

import json
from dataclasses import dataclass
from pathlib import Path

import typst

from backedcv.domain.models.layout import LineFormat, PageLayout
from backedcv.rendering.fonts import FONT_DIR, resolve_font
from backedcv.rendering.pdf_writer import page_count

TEMPLATE = Path(__file__).parent / "templates" / "mirror.typ"

# Text and spacing are tightened, never the page margins.
SCALES: tuple[float, ...] = (1.0, 0.98, 0.96, 0.94, 0.92, 0.9, 0.88, 0.86)


@dataclass(frozen=True)
class FittedMirror:
    pdf: bytes
    pages: int
    scale: float
    fits: bool  # False: even the tightest scale needs more pages than asked


def mirror_payload(
    rows: list[LineFormat], page: PageLayout, title: str = "CV", scale: float = 1.0
) -> dict:
    """The JSON the template reads. Distances are worked out here, in points, so the template
    only places boxes: the box of a line is 0.8em above its baseline and 0.2em below it."""
    payload_rows = []
    previous: LineFormat | None = None
    previous_rule_dy = 0.0

    for row in rows:
        size = row.size
        line_pitch = row.pitch or page.pitch or 1.2 * size

        rule = None
        rule_dy = 0.0
        if row.rule is not None:
            # dy: from the bottom of the row's box to the middle of the rule.
            rule_dy = row.rule.offset + row.rule.thickness / 2 - 0.2 * size
            rule = {
                "dy": round(rule_dy, 2),
                "thickness": row.rule.thickness,
                "color": row.rule.color,
            }

        gap = 0.0
        if previous is not None:
            distance = row.gap_before if row.gap_before is not None else line_pitch
            gap = distance - 0.2 * previous.size - 0.8 * size
            # The rule above already took up part of that space.
            gap -= previous_rule_dy

        payload_rows.append(
            {
                "spans": [span.model_dump() for span in row.spans],
                "tail": [span.model_dump() for span in row.tail],
                "align": row.align,
                "indent": round(row.indent, 2),
                "bullet": row.bullet,
                "bullet_indent": round(row.bullet_indent, 2),
                "size": round(size, 2),
                "font": resolve_font(row.font or page.font),
                "leading": round(max(0.0, line_pitch - size), 2),
                "gap": round(gap, 2),
                "rule": rule,
            }
        )
        previous = row
        previous_rule_dy = rule_dy

    return {
        "title": title,
        "font": resolve_font(page.font),
        "scale": scale,
        "page": {
            "width": page.width,
            "height": page.height,
            "margin_left": page.margin_left,
            "margin_right": page.margin_right,
            "margin_top": page.margin_top,
            "margin_bottom": page.margin_bottom,
            "size": page.size,
            "color": page.color,
        },
        "rows": payload_rows,
    }


def render_mirror_pdf(
    rows: list[LineFormat], page: PageLayout, title: str = "CV", scale: float = 1.0
) -> bytes:
    return typst.compile(
        TEMPLATE,
        format="pdf",
        font_paths=[str(FONT_DIR)],
        ignore_system_fonts=True,  # embedded fonts only, so the PDF looks the same on every machine
        sys_inputs={
            "data": json.dumps(mirror_payload(rows, page, title, scale), ensure_ascii=False)
        },
    )


def fit_mirror_pdf(
    rows: list[LineFormat], page: PageLayout, title: str = "CV", max_pages: int | None = None
) -> FittedMirror:
    """The CV at the first scale, from full size down, that takes at most `max_pages` pages;
    without a limit, at most the pages of the uploaded file. Nothing is ever cut: when no scale
    fits, the tightest one comes back with `fits` False."""
    limit = max_pages or page.pages
    for scale in SCALES:
        pdf = render_mirror_pdf(rows, page, title, scale)
        pages = page_count(pdf)
        if pages <= limit:
            return FittedMirror(pdf, pages, scale, True)
    return FittedMirror(pdf, pages, scale, False)
