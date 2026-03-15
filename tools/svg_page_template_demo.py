from __future__ import annotations

import argparse
from pathlib import Path

import fitz


FONT_FILES = {
    "SofiaSans-Regular": Path("assets/fonts/sofia-sans/SofiaSans-Regular.ttf"),
    "SofiaSans-Medium": Path("assets/fonts/sofia-sans/SofiaSans-Medium.ttf"),
    "SofiaSans-SemiBold": Path("assets/fonts/sofia-sans/SofiaSans-SemiBold.ttf"),
    "SofiaSans-Bold": Path("assets/fonts/sofia-sans/SofiaSans-Bold.ttf"),
    "SofiaSans-ExtraBold": Path("assets/fonts/sofia-sans/SofiaSans-ExtraBold.ttf"),
}

FONT_ALIASES = {
    "SofiaSans-Regular": "SofiaSansRegular",
    "SofiaSans-Medium": "SofiaSansMedium",
    "SofiaSans-SemiBold": "SofiaSansSemiBold",
    "SofiaSans-Bold": "SofiaSansBold",
    "SofiaSans-ExtraBold": "SofiaSansExtraBold",
}


def color_to_rgb(color: int) -> tuple[float, float, float]:
    red = ((color >> 16) & 0xFF) / 255
    green = ((color >> 8) & 0xFF) / 255
    blue = (color & 0xFF) / 255
    return (red, green, blue)


def register_fonts(page: fitz.Page) -> dict[str, str]:
    registered: dict[str, str] = {}
    for source_name, font_path in FONT_FILES.items():
        alias = FONT_ALIASES[source_name]
        page.insert_font(fontname=alias, fontfile=str(font_path))
        registered[source_name] = alias
    return registered


def choose_font(span_font: str, registered: dict[str, str]) -> str:
    if span_font in registered:
        return registered[span_font]
    if "ExtraBold" in span_font:
        return registered["SofiaSans-ExtraBold"]
    if "SemiBold" in span_font:
        return registered["SofiaSans-SemiBold"]
    if "Bold" in span_font:
        return registered["SofiaSans-Bold"]
    if "Medium" in span_font:
        return registered["SofiaSans-Medium"]
    return registered["SofiaSans-Regular"]


def render_background(svg_path: Path, width: float, height: float) -> fitz.Document:
    svg_doc = fitz.open(svg_path)
    background = fitz.open()
    page = background.new_page(width=width, height=height)
    page.draw_rect(page.rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
    pix = svg_doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=True)
    page.insert_image(page.rect, pixmap=pix, keep_proportion=False, overlay=True)
    return background


def overlay_text(source_page: fitz.Page, target_page: fitz.Page) -> None:
    registered = register_fonts(target_page)
    text = source_page.get_text("dict")

    for block in text["blocks"]:
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            for span in line.get("spans", []):
                raw_text = span.get("text", "")
                if not raw_text.strip():
                    continue

                span_font = span.get("font", "SofiaSans-Regular")
                fontname = choose_font(span_font, registered)
                draw_text = raw_text.rstrip()

                if span_font == "AbakuTLSymSans-Regular" or draw_text == "¨":
                    draw_text = "₺"
                    fontname = registered["SofiaSans-Bold"]

                target_page.insert_text(
                    span["origin"],
                    draw_text,
                    fontname=fontname,
                    fontsize=span["size"],
                    color=color_to_rgb(span["color"]),
                    overlay=True,
                )


def render_preview(doc_path: Path, output_png: Path) -> None:
    doc = fitz.open(doc_path)
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    pix.save(output_png)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Place a full-page SVG template behind a PDF page and redraw its text spans."
    )
    parser.add_argument("input_pdf", type=Path)
    parser.add_argument("svg_template", type=Path)
    parser.add_argument("output_pdf", type=Path)
    parser.add_argument("--page", type=int, default=1, help="1-based page number from the input PDF")
    parser.add_argument("--preview", type=Path, default=None, help="Optional PNG preview path")
    args = parser.parse_args()

    source_doc = fitz.open(args.input_pdf)
    source_page = source_doc[args.page - 1]
    output_doc = render_background(args.svg_template, source_page.rect.width, source_page.rect.height)
    target_page = output_doc[0]
    overlay_text(source_page, target_page)
    output_doc.save(args.output_pdf)

    if args.preview:
        render_preview(args.output_pdf, args.preview)

    print(args.output_pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
