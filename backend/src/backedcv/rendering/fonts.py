"""The open fonts bundled for rebuilt CVs, and which one stands in for a font named in a file."""

import re
from pathlib import Path

from backedcv.config import load

FONT_DIR = Path(__file__).parent / "fonts"

_STYLE_WORDS = (
    "Bold",
    "Italic",
    "Oblique",
    "Regular",
    "Medium",
    "Light",
    "Semibold",
    "SemiBold",
    "Demi",
    "Black",
    "Heavy",
    "Book",
)
_PS_SUFFIXES = ("PSMT", "PS", "MT")


def family_of(fontname: str | None) -> str | None:
    """ "ABCDEF+Cambria-BoldItalic" gives "Cambria": the family a PDF or DOCX font name
    belongs to."""
    if fontname is None or not fontname.strip():
        return None

    name = fontname.rsplit("+", 1)[-1]
    name = re.split(r"[-,]", name, maxsplit=1)[0]

    for suffix in _PS_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    removed = True
    while removed:
        removed = False
        for word in _STYLE_WORDS:
            if name.endswith(word) and len(name) - len(word) >= 3:
                name = name[: -len(word)]
                removed = True
                break

    name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name).strip()
    return name or None


def resolve_font(name: str | None) -> str:
    """The bundled family that stands in for `name`: its twin when it has one,
    else the serif or the sans fallback."""
    config = load("fonts")
    twins = config["twins"]
    fallback = config["fallback"]

    family = family_of(name) or ""
    key = "".join(char for char in family.lower() if char.isalnum())

    matches = [twin for twin in twins if key.startswith(twin)]
    if matches:
        return twins[max(matches, key=len)]

    if "sans" in key:
        return fallback["sans"]
    if any(word in key for word in fallback["serif_words"]):
        return fallback["serif"]
    return fallback["sans"]
