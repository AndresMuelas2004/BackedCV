from backedcv.domain.document_diff import apply_suggestions, document_from_cv
from backedcv.domain.mirror import mirror_rows, restyle, row_text
from backedcv.domain.models import (
    Contact,
    ContactField,
    CVEntry,
    CVLine,
    CVSection,
    ParsedCV,
    Suggestion,
    Verification,
)
from backedcv.domain.models.layout import LineFormat, Rule, TextSpan


def _name() -> CVLine:
    fmt = LineFormat(spans=[TextSpan(text="Jane Doe", bold=True)], size=18, align="center")
    return CVLine(id="L001", text="Jane Doe", fmt=fmt)


def _email() -> CVLine:
    fmt = LineFormat(spans=[TextSpan(text="jane@example.com")], align="center")
    return CVLine(id="L002", text="jane@example.com", fmt=fmt)


def _heading(line_id: str, text: str) -> CVLine:
    fmt = LineFormat(
        spans=[TextSpan(text=text, bold=True)], size=12, rule=Rule(offset=2, thickness=0.5)
    )
    return CVLine(id=line_id, text=text, fmt=fmt)


def _text(line_id: str, text: str, *, bullet: bool = False) -> CVLine:
    fmt = LineFormat(
        spans=[TextSpan(text=text)], bullet="•" if bullet else None, indent=18 if bullet else 0
    )
    return CVLine(id=line_id, text=text, fmt=fmt)


def _contact() -> Contact:
    return Contact(
        name=ContactField(value="Jane Doe", line_id="L001"),
        email=ContactField(value="jane@example.com", line_id="L002"),
    )


def _contact_section() -> CVSection:
    return CVSection(id="S00", heading_line_id=None, type="contact", line_ids=["L001", "L002"])


def _verified(
    sid: str, kind: str, target: str, after: str, before: str | None = None
) -> Suggestion:
    return Suggestion(
        id=sid,
        kind=kind,
        target=target,
        before=before,
        after=after,
        verification=Verification(status="verified"),
    )


def test_cv_without_formats_gives_none() -> None:
    cv = ParsedCV(lines=[CVLine(id="L001", text="Jane Doe"), CVLine(id="L002", text="Summary")])
    assert mirror_rows(cv, document_from_cv(cv), []) is None


def test_identity_returns_the_original_formats_in_cv_order() -> None:
    cv = ParsedCV(
        lines=[
            _name(),
            _email(),
            _heading("L003", "Experience"),
            _text("L004", "Senior Engineer"),
            _text("L005", "Built the billing API", bullet=True),
        ],
        contact=_contact(),
        sections=[
            _contact_section(),
            CVSection(
                id="S01",
                heading_line_id="L003",
                type="experience",
                line_ids=["L003", "L004", "L005"],
            ),
        ],
    )
    rows = mirror_rows(cv, document_from_cv(cv), [])
    assert rows == [line.fmt for line in cv.lines]


def test_restyle_keeps_a_bold_label() -> None:
    fmt = LineFormat(spans=[TextSpan(text="Skills:", bold=True), TextSpan(text=" Python, SQL")])
    out = restyle(fmt, "Skills: Python, SQL, Docker")
    assert [span.text for span in out.spans] == ["Skills:", " Python, SQL, Docker"]
    assert [span.bold for span in out.spans] == [True, False]


def test_restyle_keeps_the_tail_only_when_the_text_ends_with_it() -> None:
    fmt = LineFormat(
        spans=[TextSpan(text="Senior Engineer, Acme", bold=True)],
        tail=[TextSpan(text="2021 - 2024")],
    )
    kept = restyle(fmt, "Senior Engineer, Acme 2021 - 2024")
    assert kept.tail == fmt.tail
    assert row_text(kept) == "Senior Engineer, Acme 2021 - 2024"

    dropped = restyle(fmt, "Senior Engineer, Acme 2019")
    assert dropped.tail == []
    assert row_text(dropped) == "Senior Engineer, Acme 2019"


def test_restyle_keeps_original_characters_in_unchanged_words() -> None:
    fmt = LineFormat(spans=[TextSpan(text="Acme – Madrid")])
    out = restyle(fmt, "Acme - Madrid, Spain")
    assert row_text(out) == "Acme – Madrid, Spain"


def test_accepted_add_line_follows_the_last_line_of_its_entry() -> None:
    cv = ParsedCV(
        lines=[
            _name(),
            _email(),
            _heading("L003", "Experience"),
            _text("L004", "Senior Engineer"),
            _text("L005", "Acme Corp, 2021-03 - Present"),
            _text("L006", "Built the billing API", bullet=True),
            _text("L007", "Led a team of four", bullet=True),
        ],
        contact=_contact(),
        sections=[
            _contact_section(),
            CVSection(
                id="S01",
                heading_line_id="L003",
                type="experience",
                line_ids=["L003", "L004", "L005", "L006", "L007"],
            ),
        ],
        entries=[
            CVEntry(
                id="E01",
                section_id="S01",
                kind="job",
                title="Senior Engineer",
                organization="Acme Corp",
                line_ids=["L004", "L005", "L006", "L007"],
            )
        ],
    )
    added = Suggestion(
        id="S01",
        kind="add_line",
        target="E01",
        after="Shipped the reporting service",
        verification=Verification(status="verified"),
    )
    doc = apply_suggestions(document_from_cv(cv), cv, [added], ["S01"])
    rows = mirror_rows(cv, doc, [added])
    assert rows is not None
    texts = [row_text(row) for row in rows]
    index = texts.index("Shipped the reporting service")
    assert texts[index - 1] == "Led a team of four"
    assert rows[index].bullet == "•"
    assert rows[index].indent == 18


def test_headingless_section_gets_no_row_and_added_skills_copy_the_heading() -> None:
    cv = ParsedCV(
        lines=[
            _name(),
            _email(),
            _text("L003", "Backend engineer with 5 years of Python APIs."),
            _heading("L004", "EXPERIENCE"),
            _text("L005", "Built the billing API", bullet=True),
        ],
        contact=_contact(),
        sections=[
            _contact_section(),
            CVSection(id="S01", heading_line_id=None, type="summary", line_ids=["L003"]),
            CVSection(
                id="S02", heading_line_id="L004", type="experience", line_ids=["L004", "L005"]
            ),
        ],
    )
    skills = _verified("S01", "add_skill", "S99", "Python, SQL")
    doc = apply_suggestions(document_from_cv(cv), cv, [skills], ["S01"])
    rows = mirror_rows(cv, doc, [skills])
    assert rows is not None
    assert [row_text(row) for row in rows] == [
        "Jane Doe",
        "jane@example.com",
        "Backend engineer with 5 years of Python APIs.",
        "EXPERIENCE",
        "Built the billing API",
        "SKILLS",
        "Python, SQL",
    ]
    heading = rows[5]
    assert heading.spans[0].text == "SKILLS"
    assert heading.spans[0].bold
    assert heading.rule == cv.lines[3].fmt.rule


def test_lines_outside_every_section_keep_their_place_in_cv_order() -> None:
    cv = ParsedCV(
        lines=[
            _name(),
            _email(),
            _heading("L003", "Experience"),
            _text("L004", "Senior Engineer"),
            _text("L005", "Loose line"),
            _heading("L006", "Skills"),
            _text("L007", "Python"),
        ],
        contact=_contact(),
        sections=[
            _contact_section(),
            CVSection(
                id="S01", heading_line_id="L003", type="experience", line_ids=["L003", "L004"]
            ),
            CVSection(id="S02", heading_line_id="L006", type="skills", line_ids=["L006", "L007"]),
        ],
    )
    doc = document_from_cv(cv)
    assert doc.sections[-1].id == "other"
    rows = mirror_rows(cv, doc, [])
    assert rows == [line.fmt for line in cv.lines]


def test_without_keep_order_rows_follow_the_document_after_name_and_contact() -> None:
    cv = ParsedCV(
        lines=[
            _name(),
            _email(),
            _heading("L003", "Experience"),
            _text("L004", "Senior Engineer"),
            _heading("L005", "Skills"),
            _text("L006", "Python, SQL"),
        ],
        contact=_contact(),
        sections=[
            _contact_section(),
            CVSection(
                id="S01", heading_line_id="L003", type="experience", line_ids=["L003", "L004"]
            ),
            CVSection(id="S02", heading_line_id="L005", type="skills", line_ids=["L005", "L006"]),
        ],
    )
    doc = document_from_cv(cv)
    reversed_doc = doc.model_copy(update={"sections": list(reversed(doc.sections))})
    rows = mirror_rows(cv, reversed_doc, [], keep_order=False)
    assert rows is not None
    assert [row_text(row) for row in rows] == [
        "Jane Doe",
        "jane@example.com",
        "Skills",
        "Python, SQL",
        "Experience",
        "Senior Engineer",
    ]


def test_rewritten_line_keeps_its_place_and_takes_the_new_text() -> None:
    cv = ParsedCV(
        lines=[
            _name(),
            _email(),
            _heading("L003", "Experience"),
            _text("L004", "Built the API", bullet=True),
            _text("L005", "Led a team of four", bullet=True),
        ],
        contact=_contact(),
        sections=[
            _contact_section(),
            CVSection(
                id="S01",
                heading_line_id="L003",
                type="experience",
                line_ids=["L003", "L004", "L005"],
            ),
        ],
    )
    rewrite = _verified(
        "S01",
        "align_wording",
        "L004",
        "Built the billing API in Python",
        before="Built the API",
    )
    doc = apply_suggestions(document_from_cv(cv), cv, [rewrite], ["S01"])
    rows = mirror_rows(cv, doc, [rewrite])
    assert rows is not None
    assert [row_text(row) for row in rows] == [
        "Jane Doe",
        "jane@example.com",
        "Experience",
        "Built the billing API in Python",
        "Led a team of four",
    ]
    assert rows[3].bullet == "•"
