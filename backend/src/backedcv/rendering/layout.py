"""Text size and page margins of the built CV. The tighter layouts fit more on a page."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Layout:
    font_size: float  # points
    margin: float  # inches, on every side
    leading: float  # em between the lines of a paragraph


# From the standard layout to the tightest one that still reads well on paper.
LAYOUTS: tuple[Layout, ...] = (
    Layout(10.5, 0.7, 0.6),
    Layout(10.0, 0.6, 0.55),
    Layout(9.5, 0.55, 0.5),
    Layout(9.0, 0.5, 0.5),
)
STANDARD = LAYOUTS[0]
