import io

import pdfplumber
import pytest
import typst

from backedcv.rendering.fonts import FONT_DIR, family_of, resolve_font


@pytest.mark.parametrize(
    ("fontname", "family"),
    [
        ("BAAAAA+Cambria", "Cambria"),
        ("AAAAAA+Cambria-BoldItalic", "Cambria"),
        ("Calibri,Bold", "Calibri"),
        ("ArialMT", "Arial"),
        ("Arial-BoldMT", "Arial"),
        ("TimesNewRomanPSMT", "Times New Roman"),
        ("OpenSans-SemiBold", "Open Sans"),
        ("", None),
        (None, None),
    ],
)
def test_the_family_is_read_from_a_font_name(fontname, family):
    assert family_of(fontname) == family


@pytest.mark.parametrize(
    ("name", "bundled"),
    [
        ("BAAAAA+Cambria-Bold", "Caladea"),
        ("Calibri", "Carlito"),
        ("ArialMT", "Liberation Sans"),
        ("Helvetica-Oblique", "Liberation Sans"),
        ("TimesNewRomanPS-BoldMT", "Liberation Serif"),
        ("Georgia", "Liberation Serif"),
        ("NotoSans-Regular", "Liberation Sans"),
        ("SomeUnknownFont", "Liberation Sans"),
        (None, "Liberation Sans"),
    ],
)
def test_a_font_name_gets_a_bundled_family(name, bundled):
    assert resolve_font(name) == bundled


@pytest.mark.parametrize("family", ["Caladea", "Carlito", "Liberation Sans", "Liberation Serif"])
def test_every_bundled_family_has_its_four_styles(family):
    source = f'#set text(font: "{family}")\nRegular *bold* _italic_ *_both_*'.encode()

    pdf = typst.compile(source, format="pdf", font_paths=[str(FONT_DIR)], ignore_system_fonts=True)

    with pdfplumber.open(io.BytesIO(pdf)) as opened:
        names = {char["fontname"].split("+")[-1] for char in opened.pages[0].chars}
    assert len(names) == 4
    assert all(name.startswith(family.replace(" ", "")) for name in names)
