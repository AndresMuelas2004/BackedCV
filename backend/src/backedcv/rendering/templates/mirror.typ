// The uploaded CV's own look: every row carries the format read from the file (see
// mirror_writer.py). One column of real text, in reading order. Text boxes have fixed edges
// (0.8em above the baseline, 0.2em below), so the distances between baselines are exact.

#let data = json(bytes(sys.inputs.data))
#let page-data = data.page
#let k = data.scale // 1, or less when the text is tightened to fit a page limit
#let pt-of(value) = value * k * 1pt
#let ink = rgb(page-data.color)

#set document(title: data.title)
#set page(
  width: page-data.width * 1pt,
  height: page-data.height * 1pt,
  margin: (
    left: page-data.margin_left * 1pt,
    right: page-data.margin_right * 1pt,
    top: page-data.margin_top * 1pt,
    bottom: page-data.margin_bottom * 1pt,
  ),
)
#set text(
  font: data.font,
  size: pt-of(page-data.size),
  fill: ink,
  top-edge: 0.8em,
  bottom-edge: -0.2em,
  ligatures: false,
  hyphenate: false,
)
#set par(spacing: 0pt, leading: 0pt)
#set block(spacing: 0pt)
#set smartquote(enabled: false)

#let styled(span, size) = {
  let body = text(
    size: pt-of(if span.size != none { span.size } else { size }),
    weight: if span.bold { "bold" } else { "regular" },
    style: if span.italic { "italic" } else { "normal" },
    fill: if span.color != none { rgb(span.color) } else { ink },
    span.text,
  )
  if span.underline { body = underline(body) }
  if span.link != none { body = link(span.link, body) }
  body
}

#let run(spans, size) = spans.map(span => styled(span, size)).join()

#for row in data.rows {
  if row.gap != 0 { v(pt-of(row.gap)) }
  let body = run(row.spans, row.size)
  // Text set against the right edge (dates, links) keeps its own column, so the rest wraps
  // beside it.
  let content = if row.tail.len() > 0 {
    grid(columns: (1fr, auto), column-gutter: pt-of(row.size * 0.6), body, run(row.tail, row.size))
  } else { body }
  block(width: 100%, inset: (left: pt-of(row.indent)), sticky: row.rule != none, {
    set par(leading: pt-of(row.leading))
    set text(size: pt-of(row.size), font: row.font)
    set align(if row.align == "center" { center } else if row.align == "right" { right } else { left })
    if row.bullet != none { place(top + left, dx: pt-of(row.bullet_indent - row.indent), row.bullet) }
    content
  })
  if row.rule != none {
    v(pt-of(row.rule.dy))
    block(sticky: true, line(
      length: 100%,
      stroke: pt-of(row.rule.thickness) + (if row.rule.color != none { rgb(row.rule.color) } else { ink }),
    ))
  }
}
