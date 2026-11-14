from backedcv.domain.models import CVLine, LineFormat, PageLayout, Rule, TextSpan


def test_a_line_keeps_its_format_through_a_dump_and_a_load():
    fmt = LineFormat(
        spans=[TextSpan(text="Engineer", bold=True), TextSpan(text=", Acme")],
        tail=[TextSpan(text="2021 - 2024")],
        indent=12.0,
        bullet="•",
        size=10.0,
        gap_before=14.5,
        rule=Rule(offset=3.0, thickness=0.75),
    )
    line = CVLine(id="L001", text="Engineer, Acme 2021 - 2024", fmt=fmt)

    assert CVLine.model_validate(line.model_dump()) == line


def test_a_line_without_a_format_is_still_valid():
    assert CVLine(id="L001", text="Jane Doe").fmt is None


def test_the_page_layout_has_one_page_and_one_column_by_default():
    layout = PageLayout(
        width=595, height=842, margin_left=34, margin_right=34, margin_top=30, margin_bottom=30
    )

    assert (layout.pages, layout.columns) == (1, 1)
