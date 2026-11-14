"""The DOCX written in the look of the uploaded file: paragraphs, runs, indents, tabs, spacing."""

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.shared import Pt

from backedcv.domain.models.layout import LineFormat, PageLayout, Rule, TextSpan
from backedcv.rendering.mirror_docx import render_mirror_docx

PAGE = PageLayout(
    width=595,
    height=842,
    margin_left=34,
    margin_right=33,
    margin_top=30,
    margin_bottom=30,
    font="BAAAAA+Cambria",
    size=10,
    color="#111111",
    pitch=12,
)


def _open(rows, **kwargs):
    return Document(io.BytesIO(render_mirror_docx(rows, PAGE, **kwargs)))


def _near(a, b) -> bool:
    return abs(a - b) <= 200


def test_one_paragraph_per_row_with_tail_after_tab():
    rows = [
        LineFormat(spans=[TextSpan(text="Jane Doe")]),
        LineFormat(
            spans=[TextSpan(text="Engineer, Acme")],
            tail=[TextSpan(text="2021 - 2024")],
            gap_before=14,
        ),
    ]

    document = _open(rows)

    assert [p.text for p in document.paragraphs] == [
        "Jane Doe",
        "Engineer, Acme\t2021 - 2024",
    ]


def test_bold_and_italic_spans_set_runs_with_font_and_size():
    rows = [
        LineFormat(spans=[TextSpan(text="Bold", bold=True)]),
        LineFormat(spans=[TextSpan(text="Slanted", italic=True)]),
    ]

    document = _open(rows)
    bold_run = document.paragraphs[0].runs[0]
    italic_run = document.paragraphs[1].runs[0]

    assert bold_run.bold is True
    assert italic_run.italic is True
    assert bold_run.font.name == "Cambria"
    assert bold_run.font.size == Pt(10)


def test_centred_row_is_centred():
    rows = [LineFormat(spans=[TextSpan(text="Centre")], align="center")]

    document = _open(rows)

    assert document.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER


def test_bullet_row_has_marker_and_hanging_indent():
    rows = [
        LineFormat(
            spans=[TextSpan(text="Built APIs")],
            bullet="•",
            indent=13,
            bullet_indent=0,
        )
    ]

    document = _open(rows)
    paragraph = document.paragraphs[0]

    assert paragraph.text.startswith("•\t")
    assert paragraph.paragraph_format.left_indent == Pt(13)
    assert paragraph.paragraph_format.first_line_indent < 0


def test_row_with_tail_has_right_tab_stop_at_text_width():
    rows = [
        LineFormat(
            spans=[TextSpan(text="Engineer")],
            tail=[TextSpan(text="2024")],
        )
    ]

    document = _open(rows)
    stops = list(document.paragraphs[0].paragraph_format.tab_stops)

    assert any(
        stop.alignment == WD_TAB_ALIGNMENT.RIGHT and _near(stop.position, Pt(595 - 34 - 33))
        for stop in stops
    )


def test_page_size_and_margins_are_written():
    document = _open([LineFormat(spans=[TextSpan(text="x")])])
    section = document.sections[0]

    assert section.page_width == Pt(595)
    assert section.page_height == Pt(842)
    assert section.left_margin == Pt(34)


def test_row_with_rule_has_bottom_border():
    rows = [
        LineFormat(
            spans=[TextSpan(text="Experience")],
            rule=Rule(offset=2, thickness=0.5),
        )
    ]

    document = _open(rows)

    assert "w:pBdr" in document.paragraphs[0]._p.xml


def test_linked_span_becomes_hyperlink_relationship():
    rows = [LineFormat(spans=[TextSpan(text="Site", link="https://example.com")])]

    document = _open(rows)
    paragraph = document.paragraphs[0]
    links = [rel for rel in document.part.rels.values() if rel.reltype.endswith("/hyperlink")]

    assert "w:hyperlink" in paragraph._p.xml
    assert len(links) == 1
    assert links[0].target_ref == "https://example.com"


def test_scale_shrinks_sizes_but_not_page():
    rows = [LineFormat(spans=[TextSpan(text="Scaled")], size=10)]

    document = _open(rows, scale=0.9)

    assert _near(document.paragraphs[0].runs[0].font.size, Pt(9))
    assert document.sections[0].page_width == Pt(595)


def test_gap_before_becomes_space_before_and_pitch_is_exact():
    rows = [
        LineFormat(spans=[TextSpan(text="First")]),
        LineFormat(spans=[TextSpan(text="Second")], gap_before=20),
    ]

    document = _open(rows)
    fmt = document.paragraphs[1].paragraph_format

    assert _near(fmt.space_before, Pt(8))
    assert fmt.line_spacing_rule == WD_LINE_SPACING.EXACTLY
    assert _near(fmt.line_spacing, Pt(12))
