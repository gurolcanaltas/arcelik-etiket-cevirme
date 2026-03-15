from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz

RED = (0.82, 0.12, 0.2)
ORANGE = (0.98, 0.73, 0.13)
GRAY = (0.88, 0.89, 0.9)
GRAY_ALT = (0.95, 0.95, 0.95)
WHITE = (1, 1, 1)
BLACK = (0.12, 0.12, 0.12)


def money(value: str) -> str:
    return f"{value} tl"


def draw_center_text(page: fitz.Page, rect: fitz.Rect, text: str, fontname: str, fontsize: float, color: tuple[float, float, float]) -> None:
    if rect.is_empty or rect.width <= 1 or rect.height <= 1:
        return
    page.insert_textbox(rect, text, fontname=fontname, fontsize=fontsize, color=color, align=1)


def find_bbox(entries: list[dict], predicate) -> fitz.Rect:
    for entry in entries:
        if predicate(entry):
            return fitz.Rect(entry["bbox"])
    raise RuntimeError("Gerekli bbox bulunamadi.")


def main() -> int:
    if len(sys.argv) != 4:
        print("kullanim: parolu_transform_demo.py <input.pdf> <data.json> <output.pdf>")
        return 1

    input_pdf = Path(sys.argv[1])
    data_path = Path(sys.argv[2])
    output_pdf = Path(sys.argv[3])
    payload = json.loads(data_path.read_text(encoding="utf-8-sig"))[0]
    analysis_path = input_pdf.with_name(input_pdf.name + ".public.json")
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    entries = analysis["pages"][0]["entries"]

    doc = fitz.open(input_pdf)
    page = doc[0]

    page.insert_font(fontname="SofiaSansRegular", fontfile=str(Path("assets/fonts/sofia-sans/SofiaSans-Regular.ttf")))
    page.insert_font(fontname="SofiaSansBold", fontfile=str(Path("assets/fonts/sofia-sans/SofiaSans-Bold.ttf")))
    page.insert_font(fontname="SofiaSansSemiBold", fontfile=str(Path("assets/fonts/sofia-sans/SofiaSans-SemiBold.ttf")))

    header_rect = find_bbox(entries, lambda entry: entry.get("originalText") == "PEŞİNAT")
    footer_rect = find_bbox(entries, lambda entry: "Peşin Fiyatı" in entry.get("originalText", ""))

    left = 24
    right = page.rect.width - 24
    top = header_rect.y0 - 58
    bottom = min(page.rect.height - 56, footer_rect.y1 + 48)
    block = fitz.Rect(left, top, right, bottom)

    page.draw_rect(block, color=WHITE, fill=WHITE, width=0)
    page.draw_rect(block, color=RED, width=2)

    top_price_h = 38
    subtitle_h = 16
    table_header_h = 22
    bottom_label_h = 16
    bottom_band_h = 22
    row_h = max(18, (block.height - top_price_h - subtitle_h - table_header_h - bottom_label_h - bottom_band_h) / 3)

    split_x = left + block.width * 0.5
    col1 = left + block.width * 0.33
    col2 = left + block.width * 0.67

    top_price_rect = fitz.Rect(left, top, right, top + top_price_h)
    left_top = fitz.Rect(left, top, split_x, top + top_price_h)
    right_top = fitz.Rect(split_x, top, right, top + top_price_h)
    subtitle_rect = fitz.Rect(left, top_price_rect.y1, right, top_price_rect.y1 + subtitle_h)
    table_header_rect = fitz.Rect(left, subtitle_rect.y1, right, subtitle_rect.y1 + table_header_h)
    rows_top = table_header_rect.y1
    rows_bottom = rows_top + row_h * 3
    bottom_label_rect = fitz.Rect(left, rows_bottom, right, rows_bottom + bottom_label_h)
    bottom_band_rect = fitz.Rect(left, bottom_label_rect.y1, right, bottom_label_rect.y1 + bottom_band_h)

    page.draw_rect(left_top, color=RED, fill=GRAY, width=0)
    page.draw_rect(right_top, color=RED, fill=ORANGE, width=0)
    page.draw_line((left_top.x0, left_top.y1), (left_top.x1, left_top.y0), color=(0.55, 0.55, 0.55), width=1.3)
    page.draw_line((split_x, top), (split_x, bottom_band_rect.y1), color=RED, width=1)

    draw_center_text(page, fitz.Rect(left_top.x0, left_top.y0 + 4, left_top.x1, left_top.y1), money(payload["main_price"]), "SofiaSansBold", 15, BLACK)
    draw_center_text(page, fitz.Rect(right_top.x0, right_top.y0 + 4, right_top.x1, right_top.y1), money(payload["parolu_price"]), "SofiaSansBold", 15, BLACK)
    draw_center_text(page, subtitle_rect, payload.get("subtitle", "Kredi Karti ile Pesin Fiyatina 3 Taksitli Satis Fiyatidir"), "SofiaSansRegular", 6.0, BLACK)

    page.draw_rect(table_header_rect, color=RED, fill=RED, width=0)
    draw_center_text(page, fitz.Rect(left, table_header_rect.y0 + 2, col1, table_header_rect.y1), "PESINAT", "SofiaSansSemiBold", 8.4, WHITE)
    draw_center_text(page, fitz.Rect(col1, table_header_rect.y0 + 2, col2, table_header_rect.y1), "TAKSIT", "SofiaSansSemiBold", 8.4, WHITE)
    draw_center_text(page, fitz.Rect(col2, table_header_rect.y0 + 2, right, table_header_rect.y1), "TOPLAM", "SofiaSansSemiBold", 8.4, WHITE)

    plan_order = ["1+2", "1+4", "1+8"]
    for index, plan_label in enumerate(plan_order):
        row_top = rows_top + row_h * index
        row_bottom = row_top + row_h
        row_rect = fitz.Rect(left, row_top, right, row_bottom)
        fill = GRAY if index % 2 == 0 else GRAY_ALT
        page.draw_rect(row_rect, color=WHITE, fill=fill, width=0)
        page.draw_line((left, row_bottom), (right, row_bottom), color=RED, width=1)
        page.draw_line((col1, row_top), (col1, row_bottom), color=RED, width=1)
        page.draw_line((col2, row_top), (col2, row_bottom), color=RED, width=1)

        plan = payload["plans"][plan_label]
        draw_center_text(page, fitz.Rect(left + 6, row_top + 1, col1 - 6, row_bottom), money(plan["pesinat"]), "SofiaSansSemiBold", 7.6, BLACK)
        draw_center_text(page, fitz.Rect(col1 + 6, row_top + 1, col2 - 6, row_bottom), f"{plan_label.split('+')[1]}x{plan['taksit']} tl", "SofiaSansSemiBold", 7.6, BLACK)
        draw_center_text(page, fitz.Rect(col2 + 6, row_top + 1, right - 6, row_bottom), money(plan["toplam"]), "SofiaSansSemiBold", 7.6, BLACK)

    draw_center_text(page, bottom_label_rect, "Pesin Fiyati", "SofiaSansRegular", 6.6, BLACK)
    page.draw_rect(fitz.Rect(left, bottom_band_rect.y0, split_x, bottom_band_rect.y1), color=RED, fill=GRAY, width=0)
    page.draw_rect(fitz.Rect(split_x, bottom_band_rect.y0, right, bottom_band_rect.y1), color=RED, fill=ORANGE, width=0)
    page.draw_line((left, bottom_band_rect.y1), (split_x, bottom_band_rect.y0), color=(0.55, 0.55, 0.55), width=1.1)
    draw_center_text(page, fitz.Rect(left + 8, bottom_band_rect.y0 + 1, split_x - 8, bottom_band_rect.y1), money(payload["main_price"]), "SofiaSansSemiBold", 7.6, BLACK)
    draw_center_text(page, fitz.Rect(split_x + 8, bottom_band_rect.y0 + 1, right - 8, bottom_band_rect.y1), money(payload["parolu_price"]), "SofiaSansSemiBold", 7.6, BLACK)

    note_rect = fitz.Rect(left, bottom_band_rect.y1 + 2, right, min(bottom - 4, page.rect.height - 8))
    draw_center_text(page, note_rect, payload.get("note", "Belirtilen fiyatlar Oliz mobil uygulamasina ozeldir."), "SofiaSansRegular", 5.4, BLACK)

    doc.save(output_pdf)
    print(output_pdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

