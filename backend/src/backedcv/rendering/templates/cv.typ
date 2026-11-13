// ATS-safe CV: one column, plain text, no tables, images, framed boxes or headers.
// Rules and grey text are decoration only: the words stay in one column, in order.
// The document arrives as JSON in sys.inputs.data (see pdf_writer.py), so strings need no escaping.

#let cv = json(bytes(sys.inputs.data))
// Text size (pt), page margin (in) and line spacing (em) arrive with the document, see
// pdf_writer.py; the standard layout applies when they are left out.
#let layout = json(bytes(sys.inputs.at(
  "layout",
  default: "{\"font_size\": 10.5, \"margin\": 0.7, \"leading\": 0.6}",
)))
#let base = layout.font_size * 1pt
#let name = cv.contact.name
#let muted = rgb("#566170") // the app's muted text colour, also used for the rules

// Consecutive bullets of one entry become one list, so they share a single spacing.
#let group-rows(rows) = {
  let groups = ()
  for row in rows {
    let previous = groups.at(groups.len() - 1, default: none)
    if row.kind == "bullet" and previous != none and previous.kind == "bullet" {
      groups = groups.slice(0, -1) + ((kind: "bullet", texts: previous.texts + (row.text,)),)
    } else {
      groups.push((kind: row.kind, texts: (row.text,)))
    }
  }
  groups
}

#set document(title: if name != none { name } else { "CV" })
#set page(paper: "a4", margin: layout.margin * 1in)
#set text(font: "Libertinus Serif", size: base, ligatures: false, hyphenate: false)
#set par(leading: layout.leading * 1em, spacing: layout.leading * 1em)
#set smartquote(enabled: false)
#set list(marker: [•], indent: 0.8em, body-indent: 0.5em)

#if name != none [
  #block(below: 0.6em)[#text(size: base * 1.7, weight: "bold")[#name]]
]

#if cv.contact.headline != none [
  #par[#cv.contact.headline]
]

// Details are unbreakable boxes joined by space, not a separator character: a wrapped line never
// ends with a stray bar. Blank details are skipped.
#let details = cv.contact.details.filter(detail => detail.trim() != "")
#if details.len() > 0 [
  #block(above: 0.5em)[
    #text(fill: muted)[#details.map(detail => box[#detail]).join(h(1.2em))]
  ]
]

#for section in cv.sections [
  // A thin rule under each heading; the space above it separates the sections.
  #if section.heading != "" [
    #block(above: 1.2em, below: 0.7em, sticky: true)[
      #stack(
        dir: ttb,
        spacing: 0.3em,
        text(size: base * 1.1, weight: "bold")[#section.heading],
        line(length: 100%, stroke: 0.5pt + muted),
      )
    ]
  ]
  // Lines of one entry sit close together; each entry after the first gets the same gap.
  #for (index, item) in section.items.enumerate() [
    #if index > 0 [#v(1em, weak: true)]
    #for group in group-rows(item.lines) [
      #if group.kind == "bullet" [
        #list(..group.texts)
      ] else [
        #par[#group.texts.first()]
      ]
    ]
  ]
]
