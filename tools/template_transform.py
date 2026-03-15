from __future__ import annotations

import argparse
import base64
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageDraw, ImageFont
from reportlab.graphics import renderPDF, renderPM
from reportlab.lib.colors import Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as ReportLabTTFont
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
TEMPLATE_DIR = PROJECT_DIR / "assets" / "templates"
FONT_DIR = PROJECT_DIR / "assets" / "fonts" / "sofia-sans"
ICON_DIR = PROJECT_DIR / "assets" / "icons" / "tl-symbols"
OLIZ_SVG = PROJECT_DIR / "Oliz.svg"

BLACK = (0.12, 0.12, 0.12)
RED = (0.81, 0.07, 0.18)
WHITE = (1.0, 1.0, 1.0)
SOFIA_EXTRA_BOLD = FONT_DIR / "SofiaSans-ExtraBold.ttf"
SOFIA_SEMI_BOLD = FONT_DIR / "SofiaSans-SemiBold.ttf"
SOFIA_REGULAR = FONT_DIR / "SofiaSans-Regular.ttf"
TOP_TL_SVG = ICON_DIR / "ust-fiyat.svg"
SMALL_TL_SVG = ICON_DIR / "diger-fiyat.svg"

TRANSFORM_CONFIGS = {
    "parolu-to-normal": {
        "template": TEMPLATE_DIR / "parolu-to-normal-fullpage.svg",
        "top_rects": [fitz.Rect(27.27, 343.53, 392.25, 376.81)],
        "row_rects": [
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
        ],
        "bottom_rects": [fitz.Rect(27.27, 496.53, 392.25, 517.07)],
        "top_tl_offset_y": [7.4],
        "row_tl_offset_y": 8.7,
        "bottom_tl_offset_y": [8.0],
        "machine_name_rect": fitz.Rect(145.0, 20.5, 274.5, 38.5),
        "machine_type_rect": fitz.Rect(106.0, 49.0, 313.0, 76.0),
        "machine_name_clear_rect": fitz.Rect(120.0, 15.0, 300.0, 42.0),
        "machine_type_clear_rect": fitz.Rect(70.0, 44.0, 349.0, 84.0),
        "date_rect": fitz.Rect(123.5, 542.4, 224.0, 551.0),
        "production_rect": fitz.Rect(123.5, 550.4, 224.0, 559.2),
        "footer_clear_rect": fitz.Rect(122.0, 541.5, 226.0, 560.0),
    },
    "normal-to-parolu": {
        "template": TEMPLATE_DIR / "normal-to-parolu-fullpage.svg",
        "top_rects": [
            fitz.Rect(27.27, 343.53, 209.76, 376.81),
            fitz.Rect(209.76, 343.53, 392.25, 376.81),
        ],
        "row_rects": [
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
        ],
        "bottom_rects": [
            fitz.Rect(61.75, 496.53, 179.32, 517.07),
            fitz.Rect(240.98, 496.53, 358.57, 517.07),
        ],
        "top_tl_offset_y": [7.4, 7.4],
        "row_tl_offset_y": 8.7,
        "bottom_tl_offset_y": [8.0, 8.0],
        "machine_name_rect": fitz.Rect(145.0, 20.5, 274.5, 38.5),
        "machine_type_rect": fitz.Rect(106.0, 49.0, 313.0, 76.0),
        "machine_name_clear_rect": fitz.Rect(120.0, 15.0, 300.0, 42.0),
        "machine_type_clear_rect": fitz.Rect(70.0, 44.0, 349.0, 84.0),
        "date_rect": fitz.Rect(123.5, 542.4, 224.0, 551.0),
        "production_rect": fitz.Rect(123.5, 550.4, 224.0, 559.2),
        "footer_clear_rect": fitz.Rect(122.0, 541.5, 226.0, 560.0),
        "oliz_rect": fitz.Rect(28.45, 542.24, 60.85, 564.54),
    },
}
ICON_DRAWINGS: dict[str, object] = {}
RASTER_IMAGE_CACHE: dict[str, bytes] = {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply SVG-based template transforms to PDF pages.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--transforms", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        payload = apply_template_transforms(Path(args.input), Path(args.transforms), Path(args.output))
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 2

    print(json.dumps(payload, ensure_ascii=True))
    return 0


def apply_template_transforms(pdf_path: Path, spec_path: Path, output_path: Path) -> dict[str, Any]:
    transforms = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    if not transforms:
        raise RuntimeError("Template donusumu icin sayfa secilmedi.")

    ensure_reportlab_fonts()
    top_icon_size = svg_viewbox_size(TOP_TL_SVG)
    small_icon_size = svg_viewbox_size(SMALL_TL_SVG)

    doc = fitz.open(stream=pdf_path.read_bytes(), filetype="pdf")
    for transform in transforms:
        page_number = int(transform["pageNumber"])
        page = doc[page_number - 1]
        config = TRANSFORM_CONFIGS.get(transform["type"])
        if not config:
            raise RuntimeError(f"Bilinmeyen donusum tipi: {transform['type']}")

        footer_positions = collect_footer_positions(page)
        overlay_pdf = render_overlay_pdf(
            Path(config["template"]),
            config,
            transform["values"],
            footer_positions,
            top_icon_size,
            small_icon_size,
        )
        page.show_pdf_page(page.rect, overlay_pdf, 0, overlay=True)

    doc.save(output_path)
    return {"ok": True, "output": str(output_path), "transformed": len(transforms)}


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


def rasterize_svg(svg_path: Path, width: int = 256, height: int = 256) -> bytes:
    key = f"{svg_path}|{width}|{height}"
    if key in RASTER_IMAGE_CACHE:
        return RASTER_IMAGE_CACHE[key]

    svg_doc = fitz.open(stream=svg_path.read_bytes(), filetype="svg")
    page = svg_doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(width / page.rect.width, height / page.rect.height), alpha=True)
    png_bytes = pix.tobytes("png")
    RASTER_IMAGE_CACHE[key] = png_bytes
    return png_bytes


def rasterize_oliz_logo() -> bytes:
    key = "oliz-flat"
    if key in RASTER_IMAGE_CACHE:
        return RASTER_IMAGE_CACHE[key]

    svg = OLIZ_SVG.read_text(encoding="utf-8")
    svg = re.sub(r"fill:\s*url\(#.*?\);", "fill: #9993c7;", svg)
    svg = re.sub(r'fill="url\(#.*?\)"', 'fill="#9993c7"', svg)
    drawing = svg2rlg(BytesIO(svg.encode("utf-8")))
    png_bytes = renderPM.drawToString(drawing, fmt="PNG")
    RASTER_IMAGE_CACHE[key] = png_bytes
    return png_bytes


def price_layout(rect: fitz.Rect, text: str, number_font: str, number_size: float, currency_width: float, gap: float) -> tuple[float, float]:
    number_width = pdfmetrics.stringWidth(text, number_font, number_size)
    total_width = number_width + gap + currency_width
    start_x = ((rect.x0 + rect.x1) / 2) - (total_width / 2)
    currency_x = start_x + number_width + gap
    return start_x, currency_x


def render_overlay_pdf(
    svg_path: Path,
    config: dict[str, Any],
    values: dict[str, Any],
    footer_positions: dict[str, tuple[float, float, float, float] | None],
    top_icon_size: tuple[float, float],
    small_icon_size: tuple[float, float],
) -> fitz.Document:
    drawing = svg2rlg(str(svg_path))
    embedded_images = extract_embedded_images(svg_path)
    buffer = BytesIO()
    page_height = drawing.height
    pdf_canvas = canvas.Canvas(buffer, pagesize=(drawing.width, drawing.height))
    renderPDF.draw(drawing, pdf_canvas, 0, 0)

    for image in embedded_images:
        draw_y = page_height - image["y"] - image["height"]
        pdf_canvas.drawImage(
            ImageReader(BytesIO(image["data"])),
            image["x"],
            draw_y,
            width=image["width"],
            height=image["height"],
            mask="auto",
        )

    pdf_canvas.setFillColor(Color(*BLACK))

    def draw_price(rect: fitz.Rect, text: str, font_name: str, font_size: float, icon_width: float, gap: float) -> None:
        start_x, _ = price_layout(rect, text, font_name, font_size, icon_width, gap)
        center_y = page_height - rect.y0 - (rect.height * 0.56)
        baseline = center_y - (font_size * 0.32)
        pdf_canvas.setFont(font_name, font_size)
        pdf_canvas.drawString(start_x, baseline, text)

    def draw_tl_icon(rect: fitz.Rect, text: str, font_name: str, font_size: float, icon_svg: Path, icon_width: float, icon_height: float, gap: float, offset_y: float) -> None:
        _, currency_x = price_layout(rect, text, font_name, font_size, icon_width, gap)
        icon_drawing = get_icon_drawing(icon_svg)
        draw_y = page_height - rect.y0 - offset_y - icon_height
        renderPDF.draw(icon_drawing, pdf_canvas, currency_x, draw_y)

    top_values = [values.get("mainPrice", "")]
    if len(config["top_rects"]) > 1:
        top_values.append(values.get("paroluPrice", ""))

    for rect, text, offset in zip(config["top_rects"], top_values, config["top_tl_offset_y"]):
        if not text:
            continue
        draw_price(rect, str(text), "SofiaSansExtraBold", 24, top_icon_size[0], 0.8)
        draw_tl_icon(rect, str(text), "SofiaSansExtraBold", 24, TOP_TL_SVG, top_icon_size[0], top_icon_size[1], 0.8, float(offset))

    rows = values.get("rows", [])
    for row_rects, row_values in zip(config["row_rects"], rows):
        for rect, key in zip(row_rects, ("pesinat", "taksit", "toplam")):
            text = str(row_values.get(key, "") or "")
            if not text:
                continue
            draw_price(rect, text, "SofiaSansSemiBold", 15, small_icon_size[0], 1.2)
            draw_tl_icon(rect, text, "SofiaSansSemiBold", 15, SMALL_TL_SVG, small_icon_size[0], small_icon_size[1], 1.2, float(config["row_tl_offset_y"]))

    bottom_values = [values.get("mainPrice", "")]
    if len(config["bottom_rects"]) > 1:
        bottom_values.append(values.get("paroluPrice", ""))

    for rect, text, offset in zip(config["bottom_rects"], bottom_values, config["bottom_tl_offset_y"]):
        if not text:
            continue
        draw_price(rect, str(text), "SofiaSansSemiBold", 15, small_icon_size[0], 1.2)
        draw_tl_icon(rect, str(text), "SofiaSansSemiBold", 15, SMALL_TL_SVG, small_icon_size[0], small_icon_size[1], 1.2, float(offset))

    for footer_key, font_size, fallback_key in (
        ("date", 7.9, "date_rect"),
        ("productionPlace", 7.9, "production_rect"),
    ):
        bbox = footer_positions.get(footer_key) or tuple(config[fallback_key])
        text = str(values.get(footer_key, "") or "")
        if not bbox or not text:
            continue
        rect = fitz.Rect(bbox)
        baseline = page_height - rect.y1 + 1.6
        pdf_canvas.setFont("SofiaSansRegular", font_size)
        pdf_canvas.drawString(rect.x0 + 0.6, baseline, text)

    pdf_canvas.save()
    return fitz.open(stream=buffer.getvalue(), filetype="pdf")


def extract_embedded_images(svg_path: Path) -> list[dict[str, Any]]:
    content = svg_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'<image[^>]*width="(?P<width>[\d.]+)"[^>]*height="(?P<height>[\d.]+)"[^>]*transform="translate\((?P<x>[\d.]+)\s+(?P<y>[\d.]+)\)\s+scale\((?P<scale>[\d.]+)\)"[^>]*xlink:href="data:image/png;base64,(?P<data>[^"]+)"',
        re.IGNORECASE | re.DOTALL,
    )

    images = []
    for match in pattern.finditer(content):
        scale = float(match.group("scale"))
        images.append(
            {
                "x": float(match.group("x")),
                "y": float(match.group("y")),
                "width": float(match.group("width")) * scale,
                "height": float(match.group("height")) * scale,
                "data": base64.b64decode(re.sub(r"\s+", "", match.group("data"))),
            }
        )

    return images


def draw_centered_text(
    pdf_canvas: canvas.Canvas,
    rect: fitz.Rect,
    page_height: float,
    text: str,
    font_name: str,
    font_size: float,
    rgb: tuple[float, float, float],
) -> None:
    if not text:
        return

    text_width = pdfmetrics.stringWidth(text, font_name, font_size)
    start_x = ((rect.x0 + rect.x1) / 2) - (text_width / 2)
    center_y = page_height - rect.y0 - (rect.height * 0.52)
    baseline = center_y - (font_size * 0.32)
    pdf_canvas.setFillColor(Color(*rgb))
    pdf_canvas.setFont(font_name, font_size)
    pdf_canvas.drawString(start_x, baseline, text)
    pdf_canvas.setFillColor(Color(*BLACK))


def fill_rect(
    pdf_canvas: canvas.Canvas,
    page_height: float,
    rect: fitz.Rect,
    rgb: tuple[float, float, float],
) -> None:
    pdf_canvas.setFillColor(Color(*rgb))
    pdf_canvas.rect(rect.x0, page_height - rect.y1, rect.width, rect.height, stroke=0, fill=1)
    pdf_canvas.setFillColor(Color(*BLACK))


def draw_footer_line(
    pdf_canvas: canvas.Canvas,
    rect: fitz.Rect,
    page_height: float,
    text: str,
    font_size: float,
) -> None:
    if not text.strip():
        return
    baseline = page_height - rect.y1 + 1.6
    pdf_canvas.setFont("SofiaSansRegular", font_size)
    pdf_canvas.drawString(rect.x0 + 0.6, baseline, text)


def render_text_image(
    text: str,
    font_path: Path,
    font_size: float,
    rgb: tuple[float, float, float],
    width: int,
    height: int,
    align: str,
) -> bytes:
    image = Image.new("RGBA", (max(width, 4), max(height, 4)), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), max(1, int(round(font_size * 4))))
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (image.width - text_width) // 2 if align == "center" else 2
    y = max(0, (image.height - text_height) // 2 - bbox[1] // 2)
    color = tuple(int(channel * 255) for channel in rgb) + (255,)
    draw.text((x, y), text, fill=color, font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def draw_page_overlays(page: fitz.Page, config: dict[str, Any], values: dict[str, Any]) -> None:
    page.draw_rect(config["machine_name_clear_rect"], color=None, fill=RED, overlay=True)
    page.insert_image(
        config["machine_name_rect"],
        stream=render_text_image(
            str(values.get("machineName", "") or ""),
            SOFIA_SEMI_BOLD,
            12,
            WHITE,
            int(config["machine_name_rect"].width * 4),
            int(config["machine_name_rect"].height * 4),
            "center",
        ),
        overlay=True,
    )

    page.draw_rect(config["machine_type_clear_rect"], color=None, fill=WHITE, overlay=True)
    page.insert_image(
        config["machine_type_rect"],
        stream=render_text_image(
            str(values.get("machineType", "") or ""),
            SOFIA_EXTRA_BOLD,
            18,
            RED,
            int(config["machine_type_rect"].width * 4),
            int(config["machine_type_rect"].height * 4),
            "center",
        ),
        overlay=True,
    )

    page.draw_rect(config["footer_clear_rect"], color=None, fill=WHITE, overlay=True)
    page.insert_image(
        config["date_rect"],
        stream=render_text_image(
            f"Fiyat de?i?iklik tarihi {str(values.get('date', '') or '').strip()}",
            SOFIA_REGULAR,
            7.9,
            BLACK,
            int(config["date_rect"].width * 6),
            int(config["date_rect"].height * 6),
            "left",
        ),
        overlay=True,
    )
    page.insert_image(
        config["production_rect"],
        stream=render_text_image(
            f"?retim Yeri: {str(values.get('productionPlace', '') or '').strip()}",
            SOFIA_REGULAR,
            7.9,
            BLACK,
            int(config["production_rect"].width * 8),
            int(config["production_rect"].height * 6),
            "left",
        ),
        overlay=True,
    )

    oliz_rect = config.get("oliz_rect")
    if oliz_rect and OLIZ_SVG.exists():
        page.insert_image(oliz_rect, stream=rasterize_oliz_logo(), overlay=True)


def collect_footer_positions(page: fitz.Page) -> dict[str, tuple[float, float, float, float] | None]:
    date_bbox = None
    place_bbox = None
    for x0, y0, x1, y1, text, *_ in page.get_text("words"):
        cleaned = str(text).strip()
        if not cleaned:
            continue
        if cleaned.count(".") == 2 and any(char.isdigit() for char in cleaned):
            date_bbox = (x0, y0, x1, y1)
        if cleaned in {"Türkiye", "TÃ¼rkiye"}:
            place_bbox = (x0, y0, x1, y1)
    return {"date": date_bbox, "productionPlace": place_bbox}


if __name__ == "__main__":
    raise SystemExit(main())
