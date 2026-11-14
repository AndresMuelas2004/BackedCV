import io

import pdfplumber
import pytest

from backedcv.domain.models.layout import LineFormat, PageLayout, Rule, TextSpan
from backedcv.rendering.mirror_writer import fit_mirror_pdf, mirror_payload, render_mirror_pdf

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
LEFT = 34
RIGHT = 595 - 33


def _read(pdf: bytes):
    """Words, lines and links of the first page, read back eagerly."""
    with pdfplumber.open(io.BytesIO(pdf)) as opened:
        page = opened.pages[0]
        words = page.extract_words(extra_attrs=["fontname", "size"])
        return words, page.lines, page.hyperlinks


def _word(words: list[dict], text: str) -> dict:
    return next(word for word in words if word["text"] == text)


def test_bold_span_uses_bold_twin_font():
    row = LineFormat(spans=[TextSpan(text="Jane", bold=True), TextSpan(text=" Doe")])

    words, _, _ = _read(render_mirror_pdf([row], PAGE))

    assert "Bold" in _word(words, "Jane")["fontname"]
    assert "Bold" not in _word(words, "Doe")["fontname"]
    assert all("Caladea" in word["fontname"] for word in words)


def test_centred_row_sits_in_the_middle_of_the_text_area():
    row = LineFormat(spans=[TextSpan(text="Centred title")], align="center")

    words, _, _ = _read(render_mirror_pdf([row], PAGE))

    ink_left = min(word["x0"] for word in words)
    ink_right = max(word["x1"] for word in words)
    assert (ink_left + ink_right) / 2 == pytest.approx((LEFT + RIGHT) / 2, abs=2)


def test_tail_is_set_against_the_right_edge():
    row = LineFormat(spans=[TextSpan(text="Engineer")], tail=[TextSpan(text="2020 - 2024")])

    words, _, _ = _read(render_mirror_pdf([row], PAGE))

    last = max(words, key=lambda word: word["x1"])
    first = min(words, key=lambda word: word["x0"])
    assert last["text"] == "2024"
    assert last["x1"] == pytest.approx(RIGHT, abs=2)
    assert first["text"] == "Engineer"
    assert first["x0"] == pytest.approx(LEFT, abs=1)


def test_bullet_and_text_follow_their_indents():
    row = LineFormat(
        spans=[TextSpan(text="Built APIs")],
        bullet="•",
        bullet_indent=1.5,
        indent=13,
    )

    words, _, _ = _read(render_mirror_pdf([row], PAGE))

    assert _word(words, "•")["x0"] == pytest.approx(LEFT + 1.5, abs=1.5)
    assert _word(words, "Built")["x0"] == pytest.approx(LEFT + 13, abs=1.5)


def test_gap_before_sets_the_distance_between_baselines():
    rows = [
        LineFormat(spans=[TextSpan(text="First")]),
        LineFormat(spans=[TextSpan(text="Second")], gap_before=14),
    ]

    words, _, _ = _read(render_mirror_pdf(rows, PAGE))

    distance = _word(words, "Second")["top"] - _word(words, "First")["top"]
    assert distance == pytest.approx(14, abs=0.6)


def test_rule_spans_the_text_area_and_keeps_the_next_distance():
    rows = [
        LineFormat(spans=[TextSpan(text="Experience")], rule=Rule(offset=3, thickness=0.75)),
        LineFormat(spans=[TextSpan(text="Next")], gap_before=15),
    ]

    words, lines, _ = _read(render_mirror_pdf(rows, PAGE))

    assert len(lines) == 1
    assert lines[0]["x0"] == pytest.approx(LEFT, abs=2)
    assert lines[0]["x1"] == pytest.approx(RIGHT, abs=2)
    distance = _word(words, "Next")["top"] - _word(words, "Experience")["top"]
    assert distance == pytest.approx(15, abs=0.6)


def test_span_link_is_kept_in_the_pdf():
    row = LineFormat(spans=[TextSpan(text="Portfolio", link="https://example.com")])

    _, _, hyperlinks = _read(render_mirror_pdf([row], PAGE))

    assert any(link["uri"] == "https://example.com" for link in hyperlinks)


def test_fit_scales_down_only_when_needed():
    rows = [LineFormat(spans=[TextSpan(text=f"Line {i}")], gap_before=12) for i in range(70)]

    fitted = fit_mirror_pdf(rows, PAGE, max_pages=1)

    assert fitted.fits is True
    assert fitted.pages == 1
    assert fitted.scale < 1.0


def test_fit_reports_when_no_scale_is_enough():
    rows = [LineFormat(spans=[TextSpan(text=f"Line {i}")], gap_before=12) for i in range(200)]

    fitted = fit_mirror_pdf(rows, PAGE, max_pages=1)

    assert fitted.fits is False
    assert fitted.pages > 1


def test_gap_after_a_ruled_row_leaves_room_for_the_rule():
    rows = [
        LineFormat(spans=[TextSpan(text="Heading")], rule=Rule(offset=3, thickness=0.75)),
        LineFormat(spans=[TextSpan(text="Body")], size=11, gap_before=15),
    ]

    payload = mirror_payload(rows, PAGE)

    rule_dy = payload["rows"][0]["rule"]["dy"]
    expected = 15 - 0.2 * 10 - 0.8 * 11 - rule_dy
    assert payload["rows"][1]["gap"] == pytest.approx(expected, abs=0.01)
