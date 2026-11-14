"""How the uploaded CV looks: the format of each line and of the page, read from the file."""

from typing import Literal

from pydantic import BaseModel, Field

Align = Literal["left", "center", "right"]


class TextSpan(BaseModel):
    """A run of text that shares one look."""

    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    size: float | None = None  # points; None: the size of its line
    color: str | None = None  # "#rrggbb"; None: the page's text colour
    link: str | None = None  # the address a click opens


class Rule(BaseModel):
    """A horizontal rule drawn under a line, as under a section heading."""

    offset: float  # points from the line's last baseline down to the top of the rule
    thickness: float  # points
    color: str | None = None  # "#rrggbb"; None: the page's text colour


class LineFormat(BaseModel):
    """The look of one CV line. `spans` and `tail` also carry its text as the file shows it."""

    spans: list[TextSpan] = Field(default_factory=list)  # the text from the left edge, in order
    tail: list[TextSpan] = Field(default_factory=list)  # text set against the right edge (dates)
    align: Align = "left"
    indent: float = 0.0  # points from the left margin to where the text starts
    bullet: str | None = None  # the marker in front of the text, when the line is a list item
    bullet_indent: float = 0.0  # points from the left margin to the marker
    size: float = 10.0  # the main text size of the line, points
    font: str | None = None  # font family as the file names it; None: the page's font
    # Points from the last baseline of the line above to this line's first baseline. None: the
    # line is the first of its page or column, so the file shows no distance.
    gap_before: float | None = None
    pitch: float | None = None  # points between the baselines of its wrapped lines; None: one line
    rule: Rule | None = None


class PageLayout(BaseModel):
    """The page of the uploaded CV, in points."""

    width: float
    height: float
    margin_left: float
    margin_right: float
    margin_top: float  # from the top edge to the top of the first line's box
    margin_bottom: float
    font: str | None = None  # font family of the running text, as the file names it
    size: float = 10.0  # size of the running text
    color: str = "#000000"  # colour of the running text
    pitch: float | None = None  # usual distance between the baselines of wrapped running text
    pages: int = 1
    columns: int = 1  # 2 when a page was read as two columns
