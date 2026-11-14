"""Write the built CV to DOCX in the look of the uploaded file: one paragraph per row, with the
runs, alignment, indents, tab stops and spacing read from that file (domain/mirror.py). The font
is named as the file names it, so Word uses it when it is installed."""

import io
from datetime import UTC, datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph

from backedcv.domain.models.layout import LineFormat, PageLayout, Rule, TextSpan
from backedcv.rendering.fonts import family_of

_ALIGN = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
}
_BLACK = "#000000"
# Paragraph properties that must follow w:pBdr in the schema; Word rejects a wrong order.
_AFTER_BORDER = (
    "w:shd",
    "w:tabs",
    "w:suppressAutoHyphens",
    "w:spacing",
    "w:ind",
    "w:contextualSpacing",
    "w:jc",
    "w:rPr",
    "w:sectPr",
    "w:pPrChange",
)


def render_mirror_docx(
    rows: list[LineFormat], page: PageLayout, title: str = "CV", scale: float = 1.0
) -> bytes:
    document = Document()

    section = document.sections[0]
    section.page_width = Pt(page.width)
    section.page_height = Pt(page.height)
    section.left_margin = Pt(page.margin_left)
    section.right_margin = Pt(page.margin_right)
    section.top_margin = Pt(page.margin_top)
    section.bottom_margin = Pt(page.margin_bottom)

    normal = document.styles["Normal"]
    normal.font.name = family_of(page.font) or "Calibri"
    normal.font.size = Pt(page.size * scale)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)

    props = document.core_properties
    props.title = title
    named = title if title != "CV" else ""
    props.author = named
    props.last_modified_by = named
    props.created = props.modified = datetime.now(UTC)

    text_width = page.width - page.margin_left - page.margin_right
    for index, row in enumerate(rows):
        _add_row(document, row, page, text_width, scale, first=index == 0)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _add_row(
    document, row: LineFormat, page: PageLayout, text_width: float, scale: float, first: bool
) -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = _ALIGN[row.align]
    fmt = paragraph.paragraph_format

    # An exact line height keeps the file's baselines; the gap is the extra room above the line.
    pitch = row.pitch or page.pitch or 1.2 * row.size
    fmt.line_spacing = Pt(pitch * scale)
    if first:
        fmt.space_before = Pt(0)
    else:
        distance = row.gap_before if row.gap_before is not None else pitch
        fmt.space_before = Pt(max(0.0, distance - pitch) * scale)

    if row.bullet:
        # Hanging indent: the marker sits at bullet_indent, the text at indent after a tab.
        fmt.left_indent = Pt(row.indent * scale)
        fmt.first_line_indent = Pt((row.bullet_indent - row.indent) * scale)
        fmt.tab_stops.add_tab_stop(Pt(row.indent * scale), WD_TAB_ALIGNMENT.LEFT)
        _add_run(paragraph, TextSpan(text=row.bullet + "\t"), row, page, scale)
    elif row.indent > 0:
        fmt.left_indent = Pt(row.indent * scale)

    for span in row.spans:
        _add_run(paragraph, span, row, page, scale)

    if row.tail:
        # The right tab stop pushes the tail (dates) to the right margin.
        fmt.tab_stops.add_tab_stop(Pt(text_width), WD_TAB_ALIGNMENT.RIGHT)
        paragraph.add_run("\t")
        for span in row.tail:
            _add_run(paragraph, span, row, page, scale)

    if row.rule is not None:
        _bottom_border(paragraph, row.rule, page)


def _add_run(
    paragraph: Paragraph, span: TextSpan, row: LineFormat, page: PageLayout, scale: float
) -> None:
    run = paragraph.add_run(span.text)
    run.bold = span.bold
    run.italic = span.italic
    run.underline = span.underline
    run.font.size = Pt((span.size or row.size) * scale)

    family = family_of(row.font or page.font)
    if family is not None:
        run.font.name = family

    # Black is the default colour, so only other colours are written.
    hex_color = span.color or page.color
    if hex_color.lower() != _BLACK:
        run.font.color.rgb = RGBColor.from_string(hex_color[1:].upper())

    if span.link:
        _link(paragraph, run, span.link)


def _link(paragraph: Paragraph, run, url: str) -> None:
    """Wraps the run in a hyperlink to `url`."""
    relation = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), relation)
    run._r.getparent().remove(run._r)
    link.append(run._r)
    paragraph._p.append(link)


def _bottom_border(paragraph: Paragraph, rule: Rule, page: PageLayout) -> None:
    border = OxmlElement("w:bottom")
    border.set(qn("w:val"), "single")
    # w:sz is in eighths of a point, and 2 (1/4 point) is the thinnest Word accepts.
    border.set(qn("w:sz"), str(max(2, round(rule.thickness * 8))))
    border.set(qn("w:space"), "1")
    border.set(qn("w:color"), (rule.color or page.color)[1:].upper())

    borders = OxmlElement("w:pBdr")
    borders.append(border)
    # The spacing and indent were set before the rule, so insert the border ahead of them.
    paragraph._p.get_or_add_pPr().insert_element_before(borders, *_AFTER_BORDER)
