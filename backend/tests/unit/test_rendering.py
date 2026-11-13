import io
from datetime import date
from pathlib import Path

import docx
from docx.shared import Inches, Pt

from backedcv.domain.builders import build_parsed_cv
from backedcv.domain.document_diff import document_from_cv
from backedcv.domain.models import CVDocument, CVLine, DocContact, DocItem, DocLine, DocSection
from backedcv.ingestion import read_cv
from backedcv.llm.drafts import CVStructureDraft, SectionDraft
from backedcv.rendering import LAYOUTS, fit_pdf, render_docx, render_pdf, roundtrip_check

CURATED_CV = Path(__file__).resolve().parents[2] / "samples" / "curated" / "cv.pdf"
HEADLINE = "Software engineer moving into AI engineering"
EXPECTED_LINES = [
    "José Muñoz",
    HEADLINE,
    "jose.munoz@example.com · +34 600 123 456 · Málaga, Spain",
    "Summary",
    "R&D engineer with C++ and C#",
    "Experience",
    "Data Engineer, Acme Corp, Jan 2020 – Present",
    "Built ETL pipelines in C++ and Python",
    "Led an R&D team of 4 people",
    "Developer, Beta Labs, 2017 – 2019",
    "Maintained C# reports for Niño and Peña clients",
    "Skills",
    "C++, C#, R&D, SQL, Python",
]


def _line(text: str, kind: str = "text") -> DocLine:
    return DocLine(text=text, origin="L001", kind=kind)


def _cv() -> CVDocument:
    return CVDocument(
        contact=DocContact(
            name="José Muñoz",
            details=["jose.munoz@example.com", "+34 600 123 456", "Málaga, Spain"],
            origins=["L001", "L002"],
            headline=HEADLINE,
            headline_origin="L003",
        ),
        sections=[
            DocSection(
                id="summary",
                type="summary",
                heading="Summary",
                items=[DocItem(id="summary-i1", lines=[_line("R&D engineer with C++ and C#")])],
            ),
            DocSection(
                id="experience",
                type="experience",
                heading="Experience",
                items=[
                    DocItem(
                        id="job-1",
                        lines=[
                            _line("Data Engineer, Acme Corp, Jan 2020 – Present"),
                            _line("Built ETL pipelines in C++ and Python", "bullet"),
                            _line("Led an R&D team of 4 people", "bullet"),
                        ],
                    ),
                    DocItem(
                        id="job-2",
                        lines=[
                            _line("Developer, Beta Labs, 2017 – 2019"),
                            _line("Maintained C# reports for Niño and Peña clients", "bullet"),
                        ],
                    ),
                ],
            ),
            DocSection(
                id="skills",
                type="skills",
                heading="Skills",
                items=[DocItem(id="skills-i1", lines=[_line("C++, C#, R&D, SQL, Python")])],
            ),
        ],
    )


def test_docx_reopens_with_every_line_in_order():
    document = docx.Document(io.BytesIO(render_docx(_cv())))

    assert [p.text for p in document.paragraphs if p.text] == EXPECTED_LINES


def test_docx_is_plain_one_column_with_no_tables_images_or_boxes():
    document = docx.Document(io.BytesIO(render_docx(_cv())))
    section = document.sections[0]
    paragraphs = {p.text: p for p in document.paragraphs}

    assert document.tables == []
    assert len(document.inline_shapes) == 0
    assert not document.element.body.xpath(".//w:txbxContent")
    assert section.header.is_linked_to_previous and section.footer.is_linked_to_previous
    assert paragraphs["Built ETL pipelines in C++ and Python"].style.name == "List Bullet"
    assert paragraphs["Experience"].runs[0].bold
    assert document.styles["Normal"].font.name == "Calibri"
    assert document.styles["Normal"].font.size == Pt(10.5)
    assert section.left_margin == Inches(0.7)


def test_pdf_reads_back_with_every_line():
    pdf = render_pdf(_cv())

    assert pdf.startswith(b"%PDF")
    ok, issues = roundtrip_check(pdf, _cv())
    assert ok, issues


def test_docx_contact_line_skips_blank_details():
    doc = _cv()
    doc.contact.details = ["jose.munoz@example.com", "", "  ", "Málaga, Spain"]

    paragraphs = [p.text for p in docx.Document(io.BytesIO(render_docx(doc))).paragraphs]

    assert "jose.munoz@example.com · Málaga, Spain" in paragraphs


def test_pdf_contact_line_skips_blank_details():
    doc = _cv()
    doc.contact.details = ["jose.munoz@example.com", "", "  ", "Málaga, Spain"]

    texts = [line.text for line in read_cv(render_pdf(doc), "cv.pdf").lines]

    assert "jose.munoz@example.com Málaga, Spain" in texts


def test_pdf_contact_wraps_between_details_without_a_separator():
    details = [
        "jose.munoz@example.com",
        "+34 600 123 456",
        "Calle Mayor 12, 29001 Málaga, Spain",
        "https://github.com/jose-munoz-example-portfolio",
        "https://linkedin.com/in/jose-munoz-example-profile",
        "https://jose-munoz.example.dev/projects/2026",
    ]
    doc = _cv()
    doc.contact.details = details

    texts = [line.text for line in read_cv(render_pdf(doc), "cv.pdf").lines]

    assert not any(all(detail in text for detail in details) for text in texts)  # it wraps
    assert all(any(detail in text for text in texts) for detail in details)  # none is split
    assert not any(text.endswith(("|", "·")) for text in texts)


CURATED_SECTIONS = {
    "Contact": "contact",
    "Education": "education",
    "Skills": "skills",
    "Languages": "languages",
    "Summary": "summary",
    "Experience": "experience",
    "Projects": "projects",
}


def _curated_draft(lines: list[CVLine]) -> CVStructureDraft:
    """The sample's structure as a model would return it; line IDs come from the read lines."""
    headings = [i for i, line in enumerate(lines) if line.text in CURATED_SECTIONS]
    sections: list[SectionDraft] = []
    for n, start in enumerate(headings):
        end = headings[n + 1] - 1 if n + 1 < len(headings) else len(lines) - 1
        sections.append(
            SectionDraft(
                type=CURATED_SECTIONS[lines[start].text],
                heading_line_id=lines[start].id,
                first_line_id=lines[start].id,
                last_line_id=lines[end].id,
            )
        )
    return CVStructureDraft(
        name_line_id=lines[0].id,  # the name is the first line of the CV
        location_line_id=next(line.id for line in lines if line.text == "Valencia, Spain"),
        sections=sections,
        entries=[],
    )


def test_curated_sample_builds_a_document_that_round_trips():
    lines = read_cv(CURATED_CV.read_bytes(), "cv.pdf").lines
    doc = document_from_cv(build_parsed_cv(lines, _curated_draft(lines), today=date(2026, 10, 11)))

    assert "other" not in [section.type for section in doc.sections]
    ok, issues = roundtrip_check(render_pdf(doc), doc)
    assert ok, issues


def test_pdf_shows_the_headline_under_the_name():
    texts = [line.text for line in read_cv(render_pdf(_cv()), "cv.pdf").lines]

    assert texts[:2] == ["José Muñoz", HEADLINE]


def test_roundtrip_accepts_a_long_link_that_wraps_at_its_hyphens():
    link = "https://github.com/" + "-".join(["nuria-calvo"] * 12)
    doc = _cv()
    doc.sections[0].items[0].lines.append(_line(link))
    pdf = render_pdf(doc)

    assert link not in [line.text for line in read_cv(pdf, "cv.pdf").lines]
    ok, issues = roundtrip_check(pdf, doc)
    assert ok, issues


def test_roundtrip_reports_a_line_missing_from_the_pdf():
    pdf = render_pdf(_cv())
    doc = _cv()
    doc.sections[0].items[0].lines.append(_line("This line was never rendered"))

    ok, issues = roundtrip_check(pdf, doc)

    assert not ok
    assert issues == ["This line was never rendered"]


def _long_cv(bullets: int) -> CVDocument:
    """One job with many one-line bullets, to fill more than a page."""
    lines = [_line("Data Engineer, Acme Corp, Jan 2020 – Present")]
    lines += [
        _line(f"Built pipeline number {i} for the analytics team in Python and SQL", "bullet")
        for i in range(bullets)
    ]
    experience = DocSection(
        id="experience",
        type="experience",
        heading="Experience",
        items=[DocItem(id="job-1", lines=lines)],
    )
    return CVDocument(contact=DocContact(name="José Muñoz"), sections=[experience])


def test_the_standard_layout_is_used_without_a_page_limit():
    fitted = fit_pdf(_cv())

    assert (fitted.pages, fitted.fits, fitted.layout) == (1, True, LAYOUTS[0])


def test_a_page_limit_tightens_the_layout_until_the_cv_fits():
    doc = _long_cv(60)

    standard = fit_pdf(doc)
    fitted = fit_pdf(doc, max_pages=1)

    assert standard.pages == 2
    assert (fitted.pages, fitted.fits) == (1, True)
    assert fitted.layout != LAYOUTS[0]
    assert roundtrip_check(fitted.pdf, doc)[0] is True


def test_a_cv_too_long_for_the_limit_comes_back_whole_and_marked():
    doc = _long_cv(200)

    fitted = fit_pdf(doc, max_pages=1)

    assert fitted.fits is False
    assert fitted.pages > 1
    assert fitted.layout == LAYOUTS[-1]
    assert roundtrip_check(fitted.pdf, doc)[0] is True  # nothing is cut


def test_the_docx_takes_the_text_size_and_margins_of_the_layout():
    tight = LAYOUTS[-1]

    document = docx.Document(io.BytesIO(render_docx(_cv(), tight)))

    assert document.styles["Normal"].font.size == Pt(tight.font_size)
    assert document.sections[0].left_margin == Inches(tight.margin)
