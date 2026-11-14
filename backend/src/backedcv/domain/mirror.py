"""The built CV as rows that look like the uploaded file. Every original line keeps its place and
its format, a rewritten line takes the format of the line it replaces, and an added line takes
the format of the line it sits under."""

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backedcv.domain.document_diff import body_line_ids
from backedcv.domain.models.cv import CVLine, ParsedCV
from backedcv.domain.models.document import CVDocument, DocLine, DocSection
from backedcv.domain.models.layout import LineFormat, TextSpan
from backedcv.domain.models.suggestion import Suggestion
from backedcv.domain.text import fold

# The pieces of a word, each with the span whose style it has.
_Word = list[tuple[str, TextSpan]]


@dataclass
class _Entry:
    source: str | None  # the original line whose place and look the row takes
    text: str | None  # None: the line exactly as the file shows it
    heading: bool
    bullet: bool
    item: int  # the document item the line is in; headings get -1


def row_text(fmt: LineFormat) -> str:
    """The text of a row as the file shows it: the spans, then the tail after one space."""
    text = "".join(span.text for span in fmt.spans)
    if fmt.tail:
        text += " " + "".join(span.text for span in fmt.tail)
    return text.strip()


def restyle(fmt: LineFormat, text: str) -> LineFormat:
    """The format of `fmt` carrying `text`. Unchanged words keep their characters and styles;
    a new word takes the style of the old word it replaces."""
    tail_words = fold("".join(span.text for span in fmt.tail)).split()
    new_words = text.split()
    tail: list[TextSpan] = []
    # The tail (a date) is kept only when the new text still ends with it.
    if tail_words and [fold(w) for w in new_words[-len(tail_words) :]] == tail_words:
        tail = [span.model_copy() for span in fmt.tail]
        new_words = new_words[: -len(tail_words)]

    old_words = _old_words(fmt)
    old_keys = [fold("".join(piece for piece, _ in word)) for word in old_words]
    matcher = difflib.SequenceMatcher(None, old_keys, [fold(w) for w in new_words], autojunk=False)
    out: list[_Word] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.extend(old_words[i1:i2])
        elif tag != "delete":
            style = _plain(_new_word_style(tag, i1, old_words, out))
            out.extend([(word, style)] for word in new_words[j1:j2])

    runs: list[tuple[dict[str, Any], str]] = []
    for index, word in enumerate(out):
        # Words are separated by one space, styled like the word that follows it.
        pieces = [(" ", word[0][1]), *word] if index else word
        for piece, style in pieces:
            key = style.model_dump(exclude={"text"})
            if runs and runs[-1][0] == key:
                runs[-1] = (key, runs[-1][1] + piece)
            else:
                runs.append((key, piece))
    spans = [TextSpan(text=piece, **key) for key, piece in runs]
    return fmt.model_copy(update={"spans": spans, "tail": tail})


def _old_words(fmt: LineFormat) -> list[_Word]:
    """The words of a line. A word may be made of pieces from several spans."""
    words: list[_Word] = []
    open_word = False
    for span in fmt.spans:
        for piece in re.findall(r"\S+|\s+", span.text):
            if piece.isspace():
                open_word = False
            else:
                if not open_word:
                    words.append([])
                    open_word = True
                words[-1].append((piece, span))
    return words


def _new_word_style(tag: str, i1: int, old_words: list[_Word], out: list[_Word]) -> TextSpan:
    """The style of new words: that of the old word they replace, else of the text before them."""
    if tag == "replace":
        return old_words[i1][0][1]
    if out:
        return out[-1][-1][1]
    if old_words:
        return old_words[0][0][1]
    return TextSpan(text="")


def _plain(style: TextSpan) -> TextSpan:
    """The style of a new word: never a link or an underline."""
    return style.model_copy(update={"underline": False, "link": None})


def mirror_rows(
    cv: ParsedCV, doc: CVDocument, suggestions: Sequence[Suggestion], *, keep_order: bool = True
) -> list[LineFormat] | None:
    """The rows to print, top to bottom. None when no line of the CV has a format (pasted text)."""
    if all(line.fmt is None for line in cv.lines):
        return None
    lines = {line.id: line for line in cv.lines}
    position = {line.id: i for i, line in enumerate(cv.lines)}
    by_id = {s.id: s for s in suggestions}
    entries = _document_entries(doc, by_id, position)
    present = {entry.source for entry in entries if entry.source is not None}
    dropped_ids = set(body_line_ids(cv)) - present
    dropped = [line for line in cv.lines if line.id in dropped_ids]
    pairs = [(entry, _render(entry, k, entries, lines, dropped)) for k, entry in enumerate(entries)]
    outside = _outside_pairs(cv, doc, by_id, lines, present, dropped_ids)
    if keep_order:
        return _cv_order(pairs, outside, position, len(cv.lines))
    return _document_order(pairs, outside, position, len(cv.lines))


def _document_entries(
    doc: CVDocument, by_id: dict[str, Suggestion], position: dict[str, int]
) -> list[_Entry]:
    """The rows the document holds, in document order."""
    entries: list[_Entry] = []
    item = 0
    for section in doc.sections:
        heading = _heading_entry(section, position)
        if heading is not None:
            entries.append(heading)
        for doc_item in section.items:
            item += 1
            for line in doc_item.lines:
                source, text = _line_source(line, by_id, position)
                bullet = line.kind == "bullet"
                entries.append(
                    _Entry(source=source, text=text, heading=False, bullet=bullet, item=item)
                )
    return entries


def _heading_entry(section: DocSection, position: dict[str, int]) -> _Entry | None:
    """The heading row of a section. A section the CV shows without a heading gets none."""
    if section.heading_origin is not None and section.heading_origin in position:
        return _Entry(source=section.heading_origin, text=None, heading=True, bullet=False, item=-1)
    if section.id.startswith("added-") and section.heading:
        return _Entry(source=None, text=section.heading, heading=True, bullet=False, item=-1)
    return None


def _line_source(
    line: DocLine, by_id: dict[str, Suggestion], position: dict[str, int]
) -> tuple[str | None, str | None]:
    """The original line a document line takes its place from, and the text it shows if the
    text is not the file's own."""
    if line.origin in position:
        return line.origin, None
    suggestion = by_id.get(line.origin)
    if (
        suggestion is not None
        and suggestion.kind == "align_wording"
        and suggestion.target in position
    ):
        return suggestion.target, line.text
    return None, line.text


def _outside_pairs(
    cv: ParsedCV,
    doc: CVDocument,
    by_id: dict[str, Suggestion],
    lines: dict[str, CVLine],
    present: set[str],
    dropped_ids: set[str],
) -> list[tuple[str, LineFormat]]:
    """The lines the document does not hold (name, contact details, headline, contact heading),
    in CV order. A rewritten headline shows its accepted wording."""
    headline = doc.contact.headline_origin
    rewrite = by_id.get(headline) if headline is not None else None
    rewritten = rewrite.target if rewrite is not None and rewrite.kind == "align_wording" else None
    pairs: list[tuple[str, LineFormat]] = []
    for line in cv.lines:
        if line.id in present or line.id in dropped_ids:
            continue
        text = doc.contact.headline if line.id == rewritten else None
        entry = _Entry(source=line.id, text=text, heading=False, bullet=False, item=0)
        pairs.append((line.id, _render(entry, 0, [], lines, [])))
    return pairs


def _cv_order(
    pairs: list[tuple[_Entry, LineFormat]],
    outside: list[tuple[str, LineFormat]],
    position: dict[str, int],
    total: int,
) -> list[LineFormat]:
    """Every row at the place of its line in the CV. An added row sits right after the nearest
    line above it, so it stays under the entry it was added to."""
    entries = [entry for entry, _ in pairs]
    keyed: list[tuple[tuple[float, int, int], LineFormat]] = []
    added = 0
    for k, (entry, row) in enumerate(pairs):
        if entry.source is not None:
            key: tuple[float, int, int] = (position[entry.source], 0, 0)
        else:
            added += 1
            key = (_anchor(entries, k, position, total), 1, added)
        keyed.append((key, row))
    keyed += [((position[line_id], 0, 0), row) for line_id, row in outside]
    keyed.sort(key=lambda pair: pair[0])
    return [row for _, row in keyed]


def _anchor(entries: list[_Entry], k: int, position: dict[str, int], total: int) -> float:
    """The CV place of an added row: after the nearest earlier line of the document, else just
    before the nearest later one, else at the end."""
    for entry in reversed(entries[:k]):
        if entry.source is not None:
            return position[entry.source]
    for entry in entries[k + 1 :]:
        if entry.source is not None:
            return position[entry.source] - 0.5
    return total


def _document_order(
    pairs: list[tuple[_Entry, LineFormat]],
    outside: list[tuple[str, LineFormat]],
    position: dict[str, int],
    total: int,
) -> list[LineFormat]:
    """The rows in document order. The lines above the first document line (name, contact) stay
    first."""
    sourced = [position[entry.source] for entry, _ in pairs if entry.source is not None]
    first = min(sourced, default=total)
    head = [row for line_id, row in outside if position[line_id] < first]
    rest = [row for line_id, row in outside if position[line_id] >= first]
    return head + [row for _, row in pairs] + rest


def _render(
    entry: _Entry,
    k: int,
    entries: list[_Entry],
    lines: dict[str, CVLine],
    dropped: list[CVLine],
) -> LineFormat:
    """The format of one row."""
    if entry.source is not None:
        line = lines[entry.source]
        base = line.fmt if line.fmt is not None else LineFormat(spans=[TextSpan(text=line.text)])
        if entry.text is None:
            return base.model_copy(deep=True)
        return restyle(base, entry.text)
    text = entry.text or ""
    if entry.heading:
        return _added_heading(text, entries, lines)
    return _added_line(text, entry, k, entries, lines, dropped)


def _added_heading(text: str, entries: list[_Entry], lines: dict[str, CVLine]) -> LineFormat:
    """A heading a suggestion added: the look of the first heading the CV has, in its case."""
    model = _heading_model(entries, lines)
    if model is None:
        return LineFormat(spans=[TextSpan(text=text, bold=True)])
    shown = text.upper() if row_text(model).isupper() else text
    return model.model_copy(update={"spans": [_styled(_main_style(model), shown)], "tail": []})


def _heading_model(entries: list[_Entry], lines: dict[str, CVLine]) -> LineFormat | None:
    for entry in entries:
        fmt = _format_of(entry.source, lines)
        if entry.heading and fmt is not None:
            return fmt
    return None


def _added_line(
    text: str,
    entry: _Entry,
    k: int,
    entries: list[_Entry],
    lines: dict[str, CVLine],
    dropped: list[CVLine],
) -> LineFormat:
    """A line a suggestion added: the look of the line above it in its item."""
    model = _line_model(entry, k, entries, lines, dropped)
    return model.model_copy(
        update={"spans": [_styled(_main_style(model), text)], "tail": [], "rule": None}
    )


def _line_model(
    entry: _Entry,
    k: int,
    entries: list[_Entry],
    lines: dict[str, CVLine],
    dropped: list[CVLine],
) -> LineFormat:
    """The format an added line copies: the nearest earlier line of its item (a bulleted one for a
    bullet, when there is one); else the first dropped line; else a plain body line."""
    earlier: list[LineFormat] = []
    for before in reversed(entries[:k]):
        fmt = _format_of(before.source, lines)
        if before.item == entry.item and fmt is not None:
            earlier.append(fmt)
    if entry.bullet:
        bulleted = next((fmt for fmt in earlier if fmt.bullet is not None), None)
        if bulleted is not None:
            return bulleted
    if earlier:
        return earlier[0]
    first_dropped = dropped[0].fmt if dropped else None
    if first_dropped is not None:
        return first_dropped
    for other in entries:
        fmt = _format_of(other.source, lines)
        if (
            not other.heading
            and fmt is not None
            and fmt.bullet is None
            and fmt.align == "left"
            and not fmt.tail
        ):
            return fmt
    return LineFormat()


def _format_of(source: str | None, lines: dict[str, CVLine]) -> LineFormat | None:
    return lines[source].fmt if source is not None else None


def _main_style(fmt: LineFormat) -> TextSpan:
    """The style of the span that covers the most characters, without a link or underline."""
    if not fmt.spans:
        return TextSpan(text="")
    widest = max(fmt.spans, key=lambda span: len(span.text))
    return widest.model_copy(update={"text": "", "underline": False, "link": None})


def _styled(style: TextSpan, text: str) -> TextSpan:
    return style.model_copy(update={"text": text})
