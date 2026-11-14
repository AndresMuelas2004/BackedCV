"""The look of PDF lines: style spans, alignment, bullets, rules, links and page layout."""

import pytest
import typst

from backedcv.ingestion import read_cv
from backedcv.ingestion.pdf_format import PageMarks, color_hex, line_shape

SOURCE = (
    """
#set page(width: 400pt, height: 300pt, margin: 30pt)
#set text(font: "Libertinus Serif", size: 10pt)
#set par(leading: 4pt, spacing: 8pt)
#align(center)[#text(size: 16pt, weight: "bold")[Jane Doe]]
*EXPERIENCE*
#line(length: 100%, stroke: 0.6pt)
*Engineer*, Acme #h(1fr) 2021 - 2024
- Built pipelines in Python that process many records every single day for the whole company """
    """and more
#link("https://example.com")[#underline[Portfolio]]
"""
)


@pytest.fixture(scope="module")
def cv():
    pdf = typst.compile(SOURCE.encode(), format="pdf", ignore_system_fonts=True)
    return read_cv(pdf, "cv.pdf")


def _line(cv, fragment: str):
    return next(line for line in cv.lines if fragment in line.text)


def test_name_line_is_centred_and_bold(cv):
    fmt = _line(cv, "Jane Doe").fmt
    assert fmt is not None
    assert fmt.align == "center"
    assert fmt.spans[0].bold


def test_section_heading_has_rule(cv):
    fmt = _line(cv, "EXPERIENCE").fmt
    assert fmt is not None and fmt.rule is not None
    assert abs(fmt.rule.thickness - 0.6) <= 0.1


def test_job_line_joins_without_space_before_comma(cv):
    line = _line(cv, "Engineer")
    assert line.text == "Engineer, Acme 2021 - 2024"
    fmt = line.fmt
    assert fmt is not None
    assert fmt.spans[0].text == "Engineer"
    assert fmt.spans[0].bold
    assert fmt.spans[1].text == ", Acme"
    assert not fmt.spans[1].bold
    assert "".join(span.text for span in fmt.tail) == "2021 - 2024"


def test_bullet_line_hangs_under_its_text(cv):
    line = _line(cv, "Built pipelines")
    fmt = line.fmt
    assert fmt is not None
    assert fmt.bullet == "•"
    assert fmt.indent > fmt.bullet_indent >= 0
    assert fmt.pitch is not None
    assert not line.text.startswith("•")


def test_link_line_keeps_address_and_underline(cv):
    fmt = _line(cv, "Portfolio").fmt
    assert fmt is not None
    assert fmt.spans[0].link == "https://example.com"
    assert fmt.spans[0].underline is True


def test_every_line_after_the_first_has_a_gap(cv):
    for line in cv.lines[1:]:
        assert line.fmt is not None
        assert line.fmt.gap_before is not None and line.fmt.gap_before > 0


def test_page_layout(cv):
    layout = cv.layout
    assert layout is not None
    assert abs(layout.margin_left - 30) <= 1
    assert layout.pages == 1
    assert layout.columns == 1
    assert layout.size == 10.0
    assert "Libertinus" in (layout.font or "")


def _word(text: str, x0: float, x1: float) -> dict:
    return {
        "text": text,
        "x0": x0,
        "x1": x1,
        "top": 100.0,
        "bottom": 110.0,
        "size": 10.0,
        "fontname": "LibertinusSerif-Regular",
        "chars": [],
    }


def test_drawn_dot_before_the_text_is_a_bullet():
    words = [_word("Built", 40.0, 70.0), _word("pipelines", 75.0, 130.0)]
    marks = PageMarks(dots=[{"x0": 30.0, "x1": 34.0, "top": 103.0, "bottom": 107.0}])
    shape = line_shape(words, 30.0, 300.0, marks, 792.0)
    assert shape.bullet == "•"
    assert "•" not in shape.text


def test_color_hex():
    assert color_hex((0, 0, 0)) == "#000000"
    assert color_hex(0.5) == "#808080"
    assert color_hex((0, 0, 0, 1)) == "#000000"
    assert color_hex(None) is None


def _read(source: str):
    pdf = typst.compile(source.encode(), format="pdf", ignore_system_fonts=True)
    return read_cv(pdf, "cv.pdf")


def test_sample_margin_right_matches_the_left_margin(cv):
    assert abs(cv.layout.margin_right - 30) <= 1


SHORT_LINES = """
#set page(width: 400pt, height: 300pt, margin: 30pt)
#set text(font: "Libertinus Serif", size: 10pt)
#align(center)[#text(size: 16pt, weight: "bold")[Jane Doe]]
#align(center)[Madrid, Spain]
Short line.
"""


def test_short_lines_keep_their_alignment_and_text_area():
    cv = _read(SHORT_LINES)
    name = _line(cv, "Jane Doe").fmt
    city = _line(cv, "Madrid").fmt
    short = _line(cv, "Short line.").fmt
    assert name is not None and name.align == "center"
    assert city is not None and city.align == "center"
    assert short is not None and short.align == "left" and short.indent == 0
    assert abs(cv.layout.margin_right - 30) <= 1


LABELS = """
#set page(width: 300pt, height: 300pt, margin: 30pt)
#set text(font: "Libertinus Serif", size: 10pt)
#set par(leading: 4pt, spacing: 4pt)
*Tools:* Python, FastAPI, Docker, Kafka, Redis

*Cloud:* AWS and Azure
"""


def test_lines_that_open_in_bold_are_not_joined():
    cv = _read(LABELS)
    assert len(cv.lines) == 2
    assert cv.lines[1].text.startswith("Cloud:")


WRAPPED = (
    """
#set page(width: 300pt, height: 300pt, margin: 30pt)
#set text(font: "Libertinus Serif", size: 10pt)
Built data pipelines in Python that process many records every single day for the whole """
    """company and keep the warehouse fresh for every team that depends on it
"""
)


def test_wrapped_regular_paragraph_is_one_line():
    cv = _read(WRAPPED)
    assert len(cv.lines) == 1
    assert cv.lines[0].text.endswith("depends on it")


LINK_AFTER_TEXT = """
#set page(width: 400pt, height: 300pt, margin: 30pt)
#set text(font: "Libertinus Serif", size: 10pt)
See #link("https://example.com")[#underline[Portfolio]] online
"""


def test_space_before_an_underlined_link_is_not_underlined():
    fmt = _read(LINK_AFTER_TEXT).lines[0].fmt
    assert fmt is not None
    assert [span.text for span in fmt.spans] == ["See ", "Portfolio", " online"]
    assert fmt.spans[1].underline and fmt.spans[1].link == "https://example.com"
    assert not fmt.spans[0].underline and fmt.spans[0].link is None
