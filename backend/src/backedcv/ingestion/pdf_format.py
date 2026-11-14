"""How the lines of a PDF page look: spans with their style, alignment, bullets, rules and links."""

from collections import Counter
from dataclasses import dataclass, field
from statistics import median

from backedcv.domain.models import Align, LineFormat, PageLayout, Rule, TextSpan
from backedcv.domain.text import normalize_text
from backedcv.ingestion.lines import BULLET_GLYPHS, joins_without_space

EDGE = 2.0  # points a line may stop short of an edge and still touch it
TIGHT = 0.1  # share of the text size: words closer than this are one word
_BOLD_HINTS = ("bold", "black", "heavy", "semibold", "demi")
_ITALIC_HINTS = ("italic", "oblique")
_DOT = "•"


@dataclass
class PageMarks:
    strokes: list[dict] = field(default_factory=list)  # thin horizontal strokes
    dots: list[dict] = field(default_factory=list)  # small filled shapes, maybe drawn bullets
    links: list[dict] = field(default_factory=list)  # clickable areas with their address


@dataclass
class Shape:
    """One physical line."""

    text: str  # the line's words, marker included when it is a glyph
    spans: list[TextSpan]  # the text from the left, without the marker
    tail: list[TextSpan]  # the text set against the right edge
    align: Align  # left, center or right
    indent: float  # from the block's left edge to the text
    bullet: str | None
    bullet_indent: float  # from the block's left edge to the marker
    size: float
    font: str | None  # the PDF font name most of the line is set in
    baseline: float  # from the page top
    x0: float  # ink of the line, marker included
    x1: float
    rule: Rule | None = None


def page_marks(page) -> PageMarks:
    """Strokes, small dots and links of a pdfplumber page."""
    marks = PageMarks()
    for obj in page.rects + page.lines + page.curves:
        x0, x1 = float(obj["x0"]), float(obj["x1"])
        top, bottom = float(obj["top"]), float(obj["bottom"])
        width, height = x1 - x0, bottom - top
        if height <= 1.5 and width >= 3:
            thickness = max(height, float(obj.get("linewidth") or 0)) or 0.5
            color = color_hex(
                obj.get("non_stroking_color") if obj.get("fill") else obj.get("stroking_color")
            )
            marks.strokes.append(
                {"x0": x0, "x1": x1, "top": top, "thickness": thickness, "color": color}
            )
        elif 1 <= width <= 8 and 1 <= height <= 8 and abs(width - height) <= 2:
            marks.dots.append({"x0": x0, "x1": x1, "top": top, "bottom": bottom})
    for link in page.hyperlinks:
        uri = link.get("uri")
        if isinstance(uri, str) and uri.startswith(("http://", "https://", "mailto:")):
            marks.links.append(
                {
                    "x0": float(link["x0"]),
                    "x1": float(link["x1"]),
                    "top": float(link["top"]),
                    "bottom": float(link["bottom"]),
                    "uri": uri,
                }
            )
    return marks


def color_hex(color) -> str | None:
    """A pdfplumber colour as "#rrggbb"; grey, RGB and CMYK are accepted."""
    if color is None:
        return None
    try:
        comps = [float(color)] if isinstance(color, (int, float)) else [float(c) for c in color]
        if len(comps) == 1:
            r = g = b = comps[0]
        elif len(comps) == 3:
            r, g, b = comps
        elif len(comps) == 4:
            c, m, y, k = comps
            r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
        else:
            return None
    except (TypeError, ValueError):
        return None
    channels = [round(min(max(v, 0.0), 1.0) * 255) for v in (r, g, b)]
    return "#{:02x}{:02x}{:02x}".format(*channels)


def line_shape(
    words: list[dict], left: float, right: float, marks: PageMarks, page_height: float
) -> Shape:
    """One physical line: its marker, its text with the style of each word, and its alignment."""
    size = round(median(float(w["size"]) for w in words), 1)
    bullet: str | None = None
    bullet_x = 0.0
    body = words
    glyph_marker = False
    if len(words) > 1 and len(words[0]["text"]) == 1 and words[0]["text"] in BULLET_GLYPHS:
        bullet, bullet_x, body = words[0]["text"], float(words[0]["x0"]), words[1:]
        glyph_marker = True
    else:
        dot = _drawn_marker(words, marks, size)
        if dot is not None:
            bullet, bullet_x = _DOT, float(dot["x0"])

    x0 = float(body[0]["x0"])
    x1 = max(float(w["x1"]) for w in body)
    width = right - left
    # A list item is never centred; its text can still look centred in a narrow block.
    centered = bullet is None and abs((x0 + x1) / 2 - (left + right) / 2) <= EDGE and x0 - left > 6
    head, tail_words = body, []
    if not centered and len(body) >= 2:
        head, tail_words = _split_tail(body, size, right, x1)
    if centered:
        align: Align = "center"
    elif not tail_words and x1 >= right - EDGE and x0 - left > 0.3 * width:
        align = "right"
    else:
        align = "left"
    indent = round(x0 - left, 1) if align == "left" else 0.0
    if indent < 0.5:
        indent = 0.0
    bullet_indent = round(bullet_x - left, 1) if bullet is not None else 0.0

    baseline = median(_baseline(w, page_height) for w in words)
    spans = _spans(head, size, baseline, marks, width)
    tail = _spans(tail_words, size, baseline, marks, width)

    text = "".join(span.text for span in spans)
    if tail:
        text += " " + "".join(span.text for span in tail)
    if glyph_marker:
        text = f"{bullet} {text}"
    return Shape(
        text=text,
        spans=spans,
        tail=tail,
        align=align,
        indent=indent,
        bullet=bullet,
        bullet_indent=bullet_indent,
        size=size,
        font=_main_font(words),
        baseline=baseline,
        # The ink starts at the drawn marker when there is one, so the margin includes it.
        x0=min(x0, bullet_x) if bullet is not None else x0,
        x1=x1,
    )


def _drawn_marker(words: list[dict], marks: PageMarks, size: float) -> dict | None:
    """A small dot just left of the line's first word, in the line's own height."""
    top = min(float(w["top"]) for w in words)
    bottom = max(float(w["bottom"]) for w in words)
    first_x0 = float(words[0]["x0"])
    for dot in marks.dots:
        middle = (dot["top"] + dot["bottom"]) / 2
        if (
            top - 1 <= middle <= bottom + 1
            and dot["x1"] <= first_x0 + 1
            and first_x0 - dot["x1"] <= 3 * size
        ):
            return dot
    return None


def _split_tail(
    body: list[dict], size: float, right: float, x1: float
) -> tuple[list[dict], list[dict]]:
    """Words set against the right edge after the widest gap, such as a date."""
    gaps = [float(body[i + 1]["x0"]) - float(body[i]["x1"]) for i in range(len(body) - 1)]
    widest = max(range(len(gaps)), key=gaps.__getitem__)
    others = gaps[:widest] + gaps[widest + 1 :]
    typical = median(others) if others else 0.25 * size
    if x1 >= right - EDGE and gaps[widest] >= max(0.6 * size, 2.5 * typical):
        return body[: widest + 1], body[widest + 1 :]
    return body, []


def _baseline(word: dict, page_height: float) -> float:
    """Where the word's letters sit, from the page top: the character matrix when it is usable."""
    chars = word.get("chars") or []
    if not chars:
        return float(word["bottom"]) - 0.22 * float(word.get("size") or 10)
    char = chars[0]
    matrix = char.get("matrix")
    if matrix and len(matrix) == 6:
        candidate = page_height - float(matrix[5])
        if float(char["top"]) - 1 <= candidate <= float(char["bottom"]) + 1:
            return candidate
    return float(char["bottom"]) - 0.22 * float(char["size"])


def _spans(
    words: list[dict], size: float, baseline: float, marks: PageMarks, width: float
) -> list[TextSpan]:
    """Consecutive words with one look form one span. A word that touches the previous one takes
    no space, so a font change inside a word does not split it."""
    spans: list[TextSpan] = []
    previous: dict | None = None
    for word in words:
        text = normalize_text(word["text"])
        if not text:
            continue
        candidate = TextSpan(text=text, **_style(word, size, baseline, marks, width))
        tight = previous is not None and (float(word["x0"]) - float(previous["x1"]) < TIGHT * size)
        if spans and _style_of(spans[-1]) == _style_of(candidate):
            spans[-1].text += text if tight else " " + text
        else:
            if not tight and spans and _is_emphasis(candidate) and not _is_emphasis(spans[-1]):
                # The space goes before the underline or link starts, so it is not underlined.
                spans[-1].text += " "
                candidate.text = text
            else:
                candidate.text = text if tight or not spans else " " + text
            spans.append(candidate)
        previous = word
    return spans


def _is_emphasis(span: TextSpan) -> bool:
    return span.underline or span.link is not None


def _style(word: dict, size: float, baseline: float, marks: PageMarks, width: float) -> dict:
    fontname = str(word.get("fontname") or "").lower()
    word_size = float(word.get("size") or size)
    chars = word.get("chars") or []
    return {
        "bold": any(hint in fontname for hint in _BOLD_HINTS),
        "italic": any(hint in fontname for hint in _ITALIC_HINTS),
        "underline": _underlined(word, size, baseline, marks, width),
        "size": None if abs(word_size - size) <= 0.25 else round(word_size, 1),
        "color": color_hex(chars[0].get("non_stroking_color")) if chars else None,
        "link": _link_at(word, marks),
    }


def _style_of(span: TextSpan) -> dict:
    return span.model_dump(exclude={"text"})


def _underlined(word: dict, size: float, baseline: float, marks: PageMarks, width: float) -> bool:
    """A thin stroke just under the word, shorter than the line, so a column rule does not count."""
    centre = (float(word["x0"]) + float(word["x1"])) / 2
    return any(
        0 <= stroke["top"] - baseline <= 0.35 * size
        and stroke["x1"] - stroke["x0"] < 0.9 * width
        and stroke["x0"] - 1 <= centre <= stroke["x1"] + 1
        for stroke in marks.strokes
    )


def _link_at(word: dict, marks: PageMarks) -> str | None:
    x = (float(word["x0"]) + float(word["x1"])) / 2
    y = (float(word["top"]) + float(word["bottom"])) / 2
    for link in marks.links:
        if link["x0"] <= x <= link["x1"] and link["top"] <= y <= link["bottom"]:
            return link["uri"]
    return None


def _main_font(words: list[dict]) -> str | None:
    """The font name with the most characters."""
    counts: Counter[str] = Counter()
    for word in words:
        if word.get("fontname"):
            counts[str(word["fontname"])] += len(word["text"])
    return counts.most_common(1)[0][0] if counts else None


def attach_rules(shapes: list[Shape], marks: PageMarks, left: float, right: float) -> None:
    """A wide stroke just under a line is that line's rule, as under a section heading."""
    for stroke in marks.strokes:
        if stroke["x1"] - stroke["x0"] < 0.6 * (right - left):
            continue
        above = [shape for shape in shapes if shape.baseline <= stroke["top"] + 0.5]
        if not above:
            continue
        shape = max(above, key=lambda s: s.baseline)
        gap = stroke["top"] - shape.baseline
        if gap <= 1.5 * shape.size and shape.rule is None:
            shape.rule = Rule(
                offset=round(gap, 2),
                thickness=round(stroke["thickness"], 2),
                color=stroke["color"],
            )


def merge_shapes(shapes: list[Shape], texts: list[str]) -> LineFormat:
    """The look of one logical line made of its physical lines, top to bottom."""
    first = shapes[0]
    spans = [span.model_copy() for span in first.spans]
    for shape, text in zip(shapes[1:], texts[1:], strict=True):
        pieces = [span.model_copy() for span in shape.spans]
        tail = [span.model_copy() for span in shape.tail]
        if pieces and tail:
            tail[0].text = " " + tail[0].text
        pieces += tail
        if not pieces:
            continue
        so_far = "".join(span.text for span in spans)
        if not joins_without_space(so_far, text):
            pieces[0].text = " " + pieces[0].text
        spans += pieces
    spans = _merge_same_style(spans)

    count = len(shapes)
    pitch = round((shapes[-1].baseline - first.baseline) / (count - 1), 2) if count > 1 else None
    return LineFormat(
        spans=spans,
        tail=[span.model_copy() for span in first.tail],
        align=first.align,
        indent=first.indent,
        bullet=first.bullet,
        bullet_indent=first.bullet_indent,
        size=first.size,
        font=first.font,
        pitch=pitch,
        rule=shapes[-1].rule,
    )


def _merge_same_style(spans: list[TextSpan]) -> list[TextSpan]:
    merged: list[TextSpan] = []
    for span in spans:
        if merged and _style_of(merged[-1]) == _style_of(span):
            merged[-1].text += span.text
        else:
            merged.append(span)
    return merged


def page_layout(
    pages: list[tuple[float, float, list[Shape], list[dict], float]], multi_column: bool
) -> PageLayout:
    """The page's margins and running text, from every page's lines, words and strokes.

    Each page carries the right-most x of its strokes as its last item.
    """
    width, height = pages[0][0], pages[0][1]
    all_shapes = [shape for _, _, shapes, _, _ in pages for shape in shapes]
    all_words = [word for _, _, _, words, _ in pages for word in words]
    stroke_right = max(stroke_x1 for *_, stroke_x1 in pages)
    ink_right = max(s.x1 for s in all_shapes)
    margin_left = min(s.x0 for s in all_shapes)
    if multi_column:
        margin_right = width - ink_right
    else:
        # A rule or a short line must not narrow the text area: the margin is never wider
        # than the left one, as side margins are nearly always equal.
        margin_right = max(0.0, min(width - max(ink_right, stroke_right), margin_left))

    tops: list[float] = []
    bottoms: list[float] = []
    for _, page_height, shapes, _, _ in pages:
        if not shapes:
            continue
        highest = min(shapes, key=lambda s: s.baseline)
        lowest = max(shapes, key=lambda s: s.baseline)
        tops.append(highest.baseline - 0.8 * highest.size)
        bottoms.append(page_height - (lowest.baseline + 0.2 * lowest.size))
    margin_top = min(tops)
    margin_bottom = max(0.0, min(margin_top, min(bottoms)))

    colors: Counter[str] = Counter()
    for word in all_words:
        chars = word.get("chars") or []
        color = color_hex(chars[0].get("non_stroking_color")) if chars else None
        if color is not None:
            colors[color] += 1
    sizes = [float(w["size"]) for w in all_words if w.get("size")]

    return PageLayout(
        width=width,
        height=height,
        margin_left=round(margin_left, 2),
        margin_right=round(margin_right, 2),
        margin_top=round(margin_top, 2),
        margin_bottom=round(margin_bottom, 2),
        font=_main_font(all_words),
        size=round(median(sizes), 1) if sizes else 10.0,
        color=colors.most_common(1)[0][0] if colors else "#000000",
        pages=len(pages),
        columns=2 if multi_column else 1,
    )
