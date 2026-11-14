"""Render a PDF CV back in its own look, with no model call: a visual check of the format the
reader takes from the file.

    uv run python scripts/mirror_preview.py path/to/cv.pdf path/to/output-folder

Writes mirror.pdf, mirror-<n>.png and original-<n>.png (one per page) and rows.json, and prints
how many pages each takes and whether the new PDF reads back.
"""

import argparse
import json
from pathlib import Path

import pdfplumber
import typst

from backedcv.domain.document_diff import document_from_cv
from backedcv.domain.mirror import mirror_rows, row_text
from backedcv.domain.models import ParsedCV
from backedcv.ingestion import read_cv
from backedcv.rendering.fonts import FONT_DIR
from backedcv.rendering.mirror_writer import TEMPLATE, fit_mirror_pdf, mirror_payload
from backedcv.rendering.roundtrip import roundtrip_lines


def typst_pngs(payload: str, ppi: int) -> list[bytes] | None:
    """The pages of the new CV as PNG, straight from Typst; None when Typst refuses."""
    try:
        result = typst.compile(
            TEMPLATE,
            format="png",
            ppi=ppi,
            font_paths=[str(FONT_DIR)],
            ignore_system_fonts=True,
            sys_inputs={"data": payload},
        )
    except Exception as error:
        print(f"Typst did not return the pages directly ({error}); using mirror.pdf instead.")
        return None
    return [result] if isinstance(result, bytes) else list(result)


def pdf_pngs(pdf_path: Path, out: Path, ppi: int) -> int:
    """One PNG per page of a PDF file, named mirror-<n>.png in the output folder."""
    with pdfplumber.open(pdf_path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            page.to_image(resolution=ppi).save(out / f"mirror-{number}.png")
        return len(pdf.pages)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a PDF CV back in its own look.")
    parser.add_argument("cv", type=Path, help="the PDF CV to read")
    parser.add_argument("out", type=Path, help="the folder for the output files")
    parser.add_argument("--ppi", type=int, default=110, help="resolution of the PNG files")
    args = parser.parse_args()

    path: Path = args.cv
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    read = read_cv(path.read_bytes(), path.name)
    if read.layout is None:
        print("The look of this file was not read.")
        raise SystemExit(1)

    cv = ParsedCV(lines=read.lines)
    doc = document_from_cv(cv)
    rows = mirror_rows(cv, doc, [])
    if rows is None:
        print("No line of this file has a format to render.")
        raise SystemExit(1)

    fitted = fit_mirror_pdf(rows, read.layout, "CV")
    (out / "mirror.pdf").write_bytes(fitted.pdf)

    payload = json.dumps(mirror_payload(rows, read.layout, "CV", fitted.scale), ensure_ascii=False)
    pngs = typst_pngs(payload, args.ppi)
    if pngs is None:
        new_pages = pdf_pngs(out / "mirror.pdf", out, args.ppi)
    else:
        new_pages = len(pngs)
        for number, png in enumerate(pngs, start=1):
            (out / f"mirror-{number}.png").write_bytes(png)

    with pdfplumber.open(path) as original:
        for number, page in enumerate(original.pages, start=1):
            page.to_image(resolution=args.ppi).save(out / f"original-{number}.png")
        original_pages = len(original.pages)

    rows_json = json.dumps([row.model_dump() for row in rows], ensure_ascii=False, indent=1)
    (out / "rows.json").write_text(rows_json, encoding="utf-8")

    reads_back, missing = roundtrip_lines(fitted.pdf, [row_text(row) for row in rows])

    print(f"original pages: {original_pages}")
    print(f"new pages: {new_pages} (scale {fitted.scale}, fits {fitted.fits})")
    print(f"rows: {len(rows)}")
    if reads_back:
        print("reads back: True")
    else:
        print(f"reads back: False {' | '.join(missing)}")


if __name__ == "__main__":
    main()
