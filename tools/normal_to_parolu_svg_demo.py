from __future__ import annotations

from io import BytesIO
from pathlib import Path

import fitz
from reportlab.lib.colors import Color
from reportlab.graphics import renderPDF
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as ReportLabTTFont
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg


TOP_LEFT_PRICE_RECT = fitz.Rect(27.27, 343.53, 209.76, 376.81)
TOP_RIGHT_PRICE_RECT = fitz.Rect(209.76, 343.53, 392.25, 376.81)
ROW_RECTS = [
    (
        fitz.Rect(27.27, 414.36, 149.04, 434.90),
        fitz.Rect(149.04, 414.36, 268.10, 434.90),
        fitz.Rect(268.10, 414.36, 392.25, 434.90),
    ),
    (
        fitz.Rect(27.27, 434.90, 149.04, 455.44),
        fitz.Rect(149.04, 434.90, 268.10, 455.44),
        fitz.Rect(268.10, 434.90, 392.25, 455.44),
    ),
    (
        fitz.Rect(27.27, 455.44, 149.04, 475.99),
        fitz.Rect(149.04, 455.44, 268.10, 475.99),
        fitz.Rect(268.10, 455.44, 392.25, 475.99),
    ),
]
BOTTOM_LEFT_PRICE_RECT = fitz.Rect(61.75, 496.53, 179.32, 517.07)
BOTTOM_RIGHT_PRICE_RECT = fitz.Rect(240.98, 496.53, 358.57, 517.07)
BLACK = (0.12, 0.12, 0.12)
SOFIA_EXTRA_BOLD = Path("assets/fonts/sofia-sans/SofiaSans-ExtraBold.ttf")
SOFIA_SEMI_BOLD = Path("assets/fonts/sofia-sans/SofiaSans-SemiBold.ttf")
SOFIA_REGULAR = Path("assets/fonts/sofia-sans/SofiaSans-Regular.ttf")
TOP_TL_SVG = Path("assets/icons/tl-symbols/ust-fiyat.svg")
SMALL_TL_SVG = Path("assets/icons/tl-symbols/diger-fiyat.svg")
TOP_TL_OFFSET_Y = 7.4
ROW_TL_OFFSET_Y = 8.7
BOTTOM_TL_OFFSET_Y = 8.0
ICON_DRAWINGS: dict[str, object] = {}


def ensure_reportlab_fonts() -> None:
    for font_name, font_path in (
        ("SofiaSansExtraBold", SOFIA_EXTRA_BOLD),
        ("SofiaSansSemiBold", SOFIA_SEMI_BOLD),
        ("SofiaSansRegular", SOFIA_REGULAR),
    ):
        if font_name in pdfmetrics.getRegisteredFontNames():
            continue
        pdfmetrics.registerFont(ReportLabTTFont(font_name, str(font_path)))


def svg_viewbox_size(svg_path: Path) -> tuple[float, float]:
    content = svg_path.read_text(encoding="utf-8")
    marker = 'viewBox="'
    start = content.index(marker) + len(marker)
    end = content.index('"', start)
    _, _, width, height = content[start:end].split()
    return float(width), float(height)


def get_icon_drawing(svg_path: Path):
    key = str(svg_path)
    if key in ICON_DRAWINGS:
        return ICON_DRAWINGS[key]
    drawing = svg2rlg(str(svg_path))
    ICON_DRAWINGS[key] = drawing
    return drawing


def price_layout(
    rect: fitz.Rect,
    text: str,
    number_font: str,
    number_size: float,
    currency_width: float,
    gap: float,
) -> tuple[float, float]:
    number_width = pdfmetrics.stringWidth(text, number_font, number_size)
    total_width = number_width + gap + currency_width
    start_x = ((rect.x0 + rect.x1) / 2) - (total_width / 2)
    currency_x = start_x + number_width + gap
    return start_x, currency_x


def render_svg_pdf(
    svg_path: Path,
    price_data: dict[str, object] | None = None,
    footer_data: list[dict[str, object]] | None = None,
) -> fitz.Document:
    drawing = svg2rlg(str(svg_path))
    buffer = BytesIO()
    page_height = drawing.height
    pdf_canvas = canvas.Canvas(buffer, pagesize=(drawing.width, drawing.height))
    renderPDF.draw(drawing, pdf_canvas, 0, 0)

    if price_data is not None:
        ensure_reportlab_fonts()
        pdf_canvas.setFillColor(Color(*BLACK))

        def draw_price(
            rect: fitz.Rect,
            text: str,
            number_font: str,
            number_size: float,
            currency_width: float,
            gap: float,
        ) -> None:
            start_x, _ = price_layout(rect, text, number_font, number_size, currency_width, gap)
            center_y = page_height - rect.y0 - (rect.height * 0.56)
            baseline = center_y - (number_size * 0.32)
            pdf_canvas.setFont(number_font, number_size)
            pdf_canvas.drawString(start_x, baseline, text)

        def draw_tl_icon(
            rect: fitz.Rect,
            text: str,
            number_font: str,
            number_size: float,
            icon_svg: Path,
            icon_width: float,
            icon_height: float,
            gap: float,
            offset_y: float,
        ) -> None:
            _, currency_x = price_layout(rect, text, number_font, number_size, icon_width, gap)
            drawing = get_icon_drawing(icon_svg)
            draw_y = page_height - rect.y0 - offset_y - icon_height
            renderPDF.draw(drawing, pdf_canvas, currency_x, draw_y)

        for rect, value in (
            (TOP_LEFT_PRICE_RECT, str(price_data["main_top"])),
            (TOP_RIGHT_PRICE_RECT, str(price_data["parolu_top"])),
        ):
            draw_price(rect, value, "SofiaSansExtraBold", 24, top_icon_size[0], 0.8)
            draw_tl_icon(rect, value, "SofiaSansExtraBold", 24, TOP_TL_SVG, top_icon_size[0], top_icon_size[1], 0.8, TOP_TL_OFFSET_Y)

        for row_rects, values in zip(ROW_RECTS, price_data["rows"]):
            for rect, value in zip(row_rects, values):
                draw_price(rect, value, "SofiaSansSemiBold", 15, small_icon_size[0], 1.2)
                draw_tl_icon(rect, value, "SofiaSansSemiBold", 15, SMALL_TL_SVG, small_icon_size[0], small_icon_size[1], 1.2, ROW_TL_OFFSET_Y)

        for rect, value in (
            (BOTTOM_LEFT_PRICE_RECT, str(price_data["main_bottom"])),
            (BOTTOM_RIGHT_PRICE_RECT, str(price_data["parolu_bottom"])),
        ):
            draw_price(rect, value, "SofiaSansSemiBold", 15, small_icon_size[0], 1.2)
            draw_tl_icon(rect, value, "SofiaSansSemiBold", 15, SMALL_TL_SVG, small_icon_size[0], small_icon_size[1], 1.2, BOTTOM_TL_OFFSET_Y)

    if footer_data:
        pdf_canvas.setFillColor(Color(*BLACK))
        for item in footer_data:
            bbox = fitz.Rect(item["bbox"])
            text = str(item["text"])
            size = float(item["size"])
            baseline = page_height - bbox.y1 + 1.6
            pdf_canvas.setFont("SofiaSansRegular", size)
            pdf_canvas.drawString(bbox.x0 + 0.6, baseline, text)

    pdf_canvas.save()
    return fitz.open(stream=buffer.getvalue(), filetype="pdf")


def collect_price_spans(page: fitz.Page) -> dict[str, object]:
    spans: list[dict[str, object]] = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                bbox = fitz.Rect(span["bbox"])
                if bbox.y0 < 340 or bbox.y1 > 520:
                    continue
                spans.append({"text": text, "bbox": bbox, "size": span["size"]})

    numeric_spans = [item for item in spans if any(ch.isdigit() for ch in item["text"])]
    main_top = min(
        [item for item in numeric_spans if item["bbox"].y0 < 390 and "." in item["text"]],
        key=lambda item: item["bbox"].x0,
    )
    main_bottom = min(
        [item for item in numeric_spans if item["bbox"].y0 > 490 and "." in item["text"]],
        key=lambda item: item["bbox"].x0,
    )

    rows: list[tuple[str, str, str]] = []
    for row_rects in ROW_RECTS:
        values: list[str] = []
        for cell_rect in row_rects:
            candidates = [
                item["text"]
                for item in numeric_spans
                if cell_rect.x0 <= item["bbox"].x0 <= cell_rect.x1 and cell_rect.y0 <= item["bbox"].y0 <= cell_rect.y1
            ]
            values.append(candidates[0] if candidates else "")
        rows.append((values[0], values[1], values[2]))

    main_value = str(main_top["text"])
    bottom_value = str(main_bottom["text"])
    return {
        "main_top": main_value,
        "parolu_top": main_value,
        "main_bottom": bottom_value,
        "parolu_bottom": bottom_value,
        "rows": rows,
    }


def collect_footer_spans(page: fitz.Page) -> list[dict[str, object]]:
    footer_values: list[dict[str, object]] = []
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        if y0 < 540 or x0 < 150:
            continue
        cleaned = str(text).strip()
        if not cleaned:
            continue
        if cleaned.count(".") == 2 and any(ch.isdigit() for ch in cleaned):
            footer_values.append({"text": cleaned, "bbox": (x0, y0, x1, y1), "size": 7.9})
            continue
        if cleaned in {"Türkiye", "TÃ¼rkiye"}:
            footer_values.append({"text": "Türkiye", "bbox": (x0, y0, x1, y1), "size": 7.9})
    return footer_values


def render_preview(pdf_path: Path, png_path: Path, page_number: int = 0) -> None:
    pdf = fitz.open(stream=pdf_path.read_bytes(), filetype="pdf")
    pix = pdf[page_number].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    png_path.write_bytes(pix.tobytes("png"))


def main() -> int:
    input_pdf = Path("tmp/pdfs/ornekk.pdf")
    svg_path = Path("tmp/pdfs/normal-to-parolu-template.svg")
    output_pdf = Path("output/pdf/ornekk-page1-normal-to-parolu-demo-v2.pdf")
    preview_png = Path("output/pdf/ornekk-page1-normal-to-parolu-demo-v2-page1.png")

    source_pdf = fitz.open(stream=input_pdf.read_bytes(), filetype="pdf")
    ensure_reportlab_fonts()
    price_data = collect_price_spans(source_pdf[0])
    footer_data = collect_footer_spans(source_pdf[0])
    global top_icon_size, small_icon_size
    top_icon_size = svg_viewbox_size(TOP_TL_SVG)
    small_icon_size = svg_viewbox_size(SMALL_TL_SVG)
    overlay_pdf = render_svg_pdf(svg_path, price_data, footer_data)
    output = fitz.open(stream=input_pdf.read_bytes(), filetype="pdf")

    page = output[0]
    page.show_pdf_page(page.rect, overlay_pdf, 0, overlay=True)

    output.save(output_pdf)
    render_preview(output_pdf, preview_png, page_number=0)
    print(output_pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
