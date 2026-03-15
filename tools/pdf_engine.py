from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import fitz
import pikepdf

TEXT_OPERATORS = {"Tj", "TJ"}
SUPPORTED_TYPE_PATTERNS = {
    "price": re.compile(r"^[\d.,xX+\- ]+[\u00a8\u20ba%]?$"),
    "date": re.compile(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$"),
    "code": re.compile(r"^[A-Z0-9][A-Z0-9 /._-]{1,24}$"),
}
COMMON_EXTRA_CHARS = set(" .,:/-+()%[]{}'\"&*_\u00a8\u20ba")
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
FALLBACK_FONT_ROOT = PROJECT_DIR / "assets" / "fonts"
_EXTERNAL_FONT_REGISTRY: dict[str, dict[str, Any]] | None = None


class PdfEditError(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze and edit PDF text content streams.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--input", required=True)
    analyze_parser.add_argument("--source", required=True)
    analyze_parser.add_argument("--file-name", required=True)
    analyze_parser.add_argument("--manifest", required=True)
    analyze_parser.add_argument("--public-output")

    replace_parser = subparsers.add_parser("replace")
    replace_parser.add_argument("--input", required=True)
    replace_parser.add_argument("--manifest", required=True)
    replace_parser.add_argument("--edits", required=True)
    replace_parser.add_argument("--output", required=True)

    args = parser.parse_args()

    try:
        if args.command == "analyze":
            payload = analyze_pdf(Path(args.input), args.source, args.file_name, Path(args.manifest), Path(args.public_output) if args.public_output else None)
            if args.public_output:
                payload = {"ok": True, "publicOutput": str(Path(args.public_output))}
        else:
            payload = replace_pdf(Path(args.input), Path(args.manifest), Path(args.edits), Path(args.output))
    except PdfEditError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 2
    except Exception as error:  # pragma: no cover
        print(json.dumps({"error": f"Beklenmeyen Python hatasi: {error}"}, ensure_ascii=True))
        return 3

    print(json.dumps(payload, ensure_ascii=True))
    return 0


def analyze_pdf(pdf_path: Path, source: str, file_name: str, manifest_path: Path, public_output_path: Path | None = None) -> dict[str, Any]:
    with pikepdf.open(pdf_path) as pdf:
        fitz_doc = fitz.open(pdf_path)
        pages = []
        manifest_pages = []

        for page_index, page in enumerate(pdf.pages):
            fitz_page = fitz_doc[page_index]
            font_profiles = build_font_profiles(page)
            instruction_entries = collect_instruction_entries(page, page_index + 1, font_profiles)
            trace_items = collect_trace_items(fitz_page)
            matched_entries = attach_trace_metadata(instruction_entries, trace_items, fitz_page.rect.width)
            finalize_supported_chars(matched_entries, font_profiles)

            pages.append(
                {
                    "pageNumber": page_index + 1,
                    "width": round_float(fitz_page.rect.width),
                    "height": round_float(fitz_page.rect.height),
                    "entries": [to_public_entry(entry) for entry in matched_entries],
                }
            )
            manifest_pages.append(
                {
                    "pageNumber": page_index + 1,
                    "entries": [to_manifest_entry(entry) for entry in matched_entries],
                }
            )

    manifest = {
        "source": source,
        "fileName": file_name,
        "pdfPath": str(pdf_path),
        "pageCount": len(manifest_pages),
        "pages": manifest_pages,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    payload = {
        "source": source,
        "fileName": file_name,
        "pageCount": len(pages),
        "pages": pages,
    }
    if public_output_path is not None:
        public_output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def replace_pdf(pdf_path: Path, manifest_path: Path, edits_path: Path, output_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    edits = json.loads(edits_path.read_text(encoding="utf-8-sig"))
    changed_edits = {
        item["id"]: normalize_text(item.get("replacementText", ""))
        for item in edits
        if item.get("id") and normalize_text(item.get("replacementText", ""))
    }
    if not changed_edits:
        raise PdfEditError("Kaydedilecek bir degisiklik bulunamadi.")

    manifest_entries = {
        entry["id"]: entry
        for page in manifest["pages"]
        for entry in page["entries"]
    }
    edit_jobs = []
    for edit_id, replacement_text in changed_edits.items():
        manifest_entry = manifest_entries.get(edit_id)
        if not manifest_entry:
            continue
        if replacement_text == normalize_text(manifest_entry.get("originalText", "")):
            continue
        edit_jobs.append((manifest_entry, replacement_text))

    if not edit_jobs:
        raise PdfEditError("Kaydedilecek bir degisiklik bulunamadi.")

    fallback_requests: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    with pikepdf.open(pdf_path) as probe_pdf:
        probe_profiles = [build_font_profiles(page) for page in probe_pdf.pages]
        for manifest_entry, replacement_text in edit_jobs:
            page_index = manifest_entry["pageNumber"] - 1
            original_profile = probe_profiles[page_index].get(manifest_entry.get("fontKey"), {})
            plan = plan_font_strategy(manifest_entry, replacement_text, original_profile)
            if plan["use_fallback"]:
                fallback_requests[page_index][plan["external_font"]["resource_key"]] = plan["external_font"]

    working_pdf_path = pdf_path
    temp_pdf_path = None
    if fallback_requests:
        temp_pdf_path = output_path.parent / f"{output_path.stem}.fontprep.pdf"
        insert_fallback_fonts(pdf_path, temp_pdf_path, fallback_requests)
        working_pdf_path = temp_pdf_path

    updated_count = 0
    try:
        with pikepdf.open(working_pdf_path) as pdf:
            for page_index, page in enumerate(pdf.pages):
                page_number = page_index + 1
                page_jobs = [job for job in edit_jobs if job[0]["pageNumber"] == page_number]
                if not page_jobs:
                    continue

                font_profiles = build_font_profiles(page)
                instructions = pikepdf.parse_content_stream(page)

                page_manifest_entries = [entry for entry in manifest["pages"][page_index]["entries"]]

                for manifest_entry, replacement_text in sorted(page_jobs, key=lambda job: job[0]["instructionIndex"], reverse=True):
                    original_profile = font_profiles.get(manifest_entry.get("fontKey"), {})
                    plan = plan_font_strategy(manifest_entry, replacement_text, original_profile)
                    target_profile = font_profiles.get(plan["resource_key"], original_profile)
                    validate_replacement(manifest_entry, replacement_text, target_profile)
                    replacement_instruction = build_replacement_instruction(manifest_entry, replacement_text, target_profile)
                    instruction_index = manifest_entry["instructionIndex"]
                    width_delta = estimate_rendered_width(manifest_entry, replacement_text, target_profile) - float((manifest_entry.get("bbox") or [0, 0, 0, 0])[2] - (manifest_entry.get("bbox") or [0, 0, 0, 0])[0])

                    if plan["use_fallback"]:
                        before_tf = build_tf_instruction(plan["resource_key"], manifest_entry.get("resourceFontSize") or 1.0)
                        after_tf = build_tf_instruction(manifest_entry.get("fontKey"), manifest_entry.get("resourceFontSize") or 1.0)
                        instructions[instruction_index:instruction_index + 1] = [before_tf, replacement_instruction, after_tf]
                    else:
                        instructions[instruction_index] = replacement_instruction

                    shift_linked_currency_symbol(instructions, page_manifest_entries, manifest_entry, width_delta)
                    updated_count += 1

                page.Contents = pdf.make_stream(pikepdf.unparse_content_stream(instructions))

            pdf.save(output_path)
    finally:
        if temp_pdf_path and temp_pdf_path.exists():
            temp_pdf_path.unlink(missing_ok=True)

    return {
        "ok": True,
        "output": str(output_path),
        "updated": updated_count,
    }


def collect_instruction_entries(page: pikepdf.Page, page_number: int, font_profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    instructions = pikepdf.parse_content_stream(page)
    entries: list[dict[str, Any]] = []
    current_font_key: str | None = None
    current_font_size = 0.0
    current_tm_index: int | None = None

    for instruction_index, instruction in enumerate(instructions):
        operator = str(instruction.operator)
        if operator == "Tf":
            current_font_key = str(instruction.operands[0])
            current_font_size = float(instruction.operands[1])
            continue

        if operator == "Tm":
            current_tm_index = instruction_index
            continue

        if operator not in TEXT_OPERATORS:
            continue

        profile = font_profiles.get(current_font_key or "", {})
        text = extract_instruction_text(instruction, profile)
        normalized_text = normalize_text(text)
        if not normalized_text:
            continue

        entry = {
            "id": f"p{page_number}-i{instruction_index}",
            "blockId": f"p{page_number}-i{instruction_index}",
            "pageNumber": page_number,
            "instructionIndex": instruction_index,
            "tmInstructionIndex": current_tm_index,
            "operator": operator,
            "originalText": text,
            "replacementText": text,
            "normalizedText": normalized_text,
            "fontKey": current_font_key,
            "resourceFontSize": round_float(current_font_size),
            "fontSize": round_float(current_font_size),
            "fontName": profile.get("fontName") or current_font_key,
            "fontSubtype": profile.get("subtype"),
            "segments": serialize_segments(instruction, profile),
            "editable": False,
            "reason": "Metin izi bulunamadi.",
            "bbox": None,
            "widthBudget": None,
            "alignment": "left",
            "supportedChars": "",
        }
        entries.append(entry)

    return entries


def collect_trace_items(page: fitz.Page) -> list[dict[str, Any]]:
    trace_items = []
    for trace_index, item in enumerate(page.get_texttrace()):
        text = "".join(chr(char[0]) for char in item.get("chars", []))
        normalized_text = normalize_text(text)
        if not normalized_text:
            continue
        bbox = [round_float(value) for value in item.get("bbox", (0, 0, 0, 0))]
        trace_items.append(
            {
                "traceIndex": trace_index,
                "text": text,
                "normalizedText": normalized_text,
                "bbox": bbox,
                "fontName": item.get("font"),
                "size": round_float(item.get("size", 0)),
            }
        )
    return trace_items


def attach_trace_metadata(entries: list[dict[str, Any]], trace_items: list[dict[str, Any]], page_width: float) -> list[dict[str, Any]]:
    cursor = 0
    used_trace_indexes: set[int] = set()

    for entry in entries:
        match_index = find_matching_trace_index(entry["normalizedText"], trace_items, cursor, used_trace_indexes)
        if match_index is None:
            match_index = find_matching_trace_index(entry["normalizedText"], trace_items, 0, used_trace_indexes)
        if match_index is None:
            entry["editable"] = False
            entry["reason"] = "Bu metin dogrudan bir gorunur metin iziyle eslesmedi."
            continue

        trace = trace_items[match_index]
        used_trace_indexes.add(match_index)
        cursor = match_index + 1
        entry["originalText"] = trace["text"]
        entry["replacementText"] = trace["text"]
        entry["normalizedText"] = trace["normalizedText"]
        entry["bbox"] = trace["bbox"]
        entry["width"] = round_float(trace["bbox"][2] - trace["bbox"][0])
        entry["height"] = round_float(trace["bbox"][3] - trace["bbox"][1])
        entry["fontName"] = trace["fontName"] or entry["fontName"]
        entry["fontSize"] = trace["size"] or entry["fontSize"]
        entry["widthBudget"] = round_float((trace["bbox"][2] - trace["bbox"][0]) * 1.25)
        entry["alignment"] = infer_alignment(trace["bbox"], page_width)

        editable, reason = evaluate_editability(entry)
        entry["editable"] = editable
        entry["reason"] = reason

    return entries


def finalize_supported_chars(entries: list[dict[str, Any]], font_profiles: dict[str, dict[str, Any]]) -> None:
    chars_by_font: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        if entry.get("fontKey"):
            chars_by_font[entry["fontKey"]].update(entry["originalText"])

    for entry in entries:
        font_key = entry.get("fontKey")
        profile_chars = set(font_profiles.get(font_key, {}).get("supported_chars", []))
        combined_chars = chars_by_font.get(font_key, set()) | profile_chars | COMMON_EXTRA_CHARS
        entry["supportedChars"] = "".join(sorted(combined_chars))


def evaluate_editability(entry: dict[str, Any]) -> tuple[bool, str]:
    text = normalize_text(entry["originalText"])
    if not entry.get("bbox"):
        return False, "Bu metnin koordinati bulunamadi."
    if len(text) > 90:
        return False, "Cok uzun metin bloklari V1 kapsaminda degil."
    if not supports_text_type(text):
        return False, "Bu metin tipi V1 duzenleme kurallari disinda."
    return True, "Duzenlenebilir"


def supports_text_type(text: str) -> bool:
    if any(pattern.match(text) for pattern in SUPPORTED_TYPE_PATTERNS.values()):
        return True
    words = text.split()
    if 1 <= len(words) <= 8 and len(text) <= 90 and re.search(r"[A-Za-zÇĞİÖŞÜçğıöşü]", text):
        return True
    return False


def validate_replacement(entry: dict[str, Any], replacement_text: str, font_profile: dict[str, Any]) -> None:
    if not replacement_text:
        raise PdfEditError(f"{entry['id']} icin bos metin kaydedilemez.")
    if not entry.get("editable"):
        raise PdfEditError(f"{entry['id']} alani duzenlenebilir degil: {entry.get('reason', 'bilinmeyen neden')}")

    supported_chars = set(font_profile.get("supported_chars", [])) | COMMON_EXTRA_CHARS
    invalid_chars = sorted({char for char in replacement_text if char not in supported_chars})
    if invalid_chars:
        raise PdfEditError(f"{entry['id']} icin desteklenmeyen karakterler var: {' '.join(invalid_chars)}")

    predicted_width = estimate_rendered_width(entry, replacement_text, font_profile)
    width_budget = float(entry.get("widthBudget") or 0)
    if width_budget and predicted_width > width_budget:
        raise PdfEditError(
            f"{entry['id']} icin yeni metin mevcut alana sigmiyor. Maksimum {round(width_budget, 2)}, tahmin {round(predicted_width, 2)}"
        )


def build_replacement_instruction(entry: dict[str, Any], replacement_text: str, font_profile: dict[str, Any]) -> pikepdf.ContentStreamInstruction:
    operator = entry["operator"]
    encoded = pikepdf.String(encode_text_bytes(replacement_text, font_profile))
    if operator == "Tj":
        return pikepdf.ContentStreamInstruction([encoded], pikepdf.Operator("Tj"))

    # Replacing with a single text run avoids carrying old kerning adjustments
    # that were tuned for the previous glyph sequence and created visible gaps.
    return pikepdf.ContentStreamInstruction([pikepdf.Array([encoded])], pikepdf.Operator("TJ"))


def extract_instruction_text(instruction: pikepdf.ContentStreamInstruction, font_profile: dict[str, Any]) -> str:
    operator = str(instruction.operator)
    if operator == "Tj":
        return decode_string_object(instruction.operands[0], font_profile)
    if operator == "TJ":
        return "".join(decode_string_object(item, font_profile) for item in instruction.operands[0] if isinstance(item, pikepdf.String))
    return ""


def serialize_segments(instruction: pikepdf.ContentStreamInstruction, font_profile: dict[str, Any]) -> list[dict[str, Any]]:
    if str(instruction.operator) == "Tj":
        return [{"kind": "text", "length": len(decode_string_object(instruction.operands[0], font_profile))}]

    segments = []
    for item in instruction.operands[0]:
        if isinstance(item, pikepdf.String):
            segments.append({"kind": "text", "length": len(decode_string_object(item, font_profile))})
        else:
            segments.append({"kind": "adjust", "value": float(item)})
    return segments


def decode_string_object(value: pikepdf.String, font_profile: dict[str, Any]) -> str:
    return decode_text_bytes(bytes(value), font_profile)


def decode_text_bytes(raw: bytes, font_profile: dict[str, Any]) -> str:
    code_map: dict[bytes, str] = font_profile.get("code_to_unicode", {})
    if not code_map:
        return raw.decode("latin1", errors="replace")

    code_lengths = font_profile.get("code_lengths", [1])
    result: list[str] = []
    index = 0
    while index < len(raw):
        matched = False
        for size in code_lengths:
            chunk = raw[index : index + size]
            if chunk in code_map:
                result.append(code_map[chunk])
                index += size
                matched = True
                break
        if not matched:
            result.append(raw[index:index + 1].decode("latin1", errors="replace"))
            index += 1
    return "".join(result)


def split_text_by_template(text: str, lengths: list[int]) -> list[str]:
    if not lengths:
        return []
    if len(lengths) == 1:
        return [text]

    total = sum(lengths)
    cursor = 0
    parts: list[str] = []
    for index, _ in enumerate(lengths):
        if index == len(lengths) - 1:
            split_at = len(text)
        else:
            cumulative = sum(lengths[: index + 1])
            split_at = round(len(text) * (cumulative / total))
        parts.append(text[cursor:split_at])
        cursor = split_at
    return parts


def find_matching_trace_index(normalized_text: str, trace_items: list[dict[str, Any]], start: int, used_indexes: set[int]) -> int | None:
    for index in range(start, len(trace_items)):
        trace = trace_items[index]
        if index in used_indexes:
            continue
        if trace["normalizedText"] == normalized_text:
            return index
    return None


def infer_alignment(bbox: list[float], page_width: float) -> str:
    center = (bbox[0] + bbox[2]) / 2
    if abs(center - (page_width / 2)) <= min(48, page_width * 0.08):
        return "center"
    if (page_width - bbox[2]) <= 32:
        return "right"
    return "left"


def estimate_rendered_width(entry: dict[str, Any], replacement_text: str, font_profile: dict[str, Any]) -> float:
    bbox = entry.get("bbox") or [0, 0, 0, 0]
    original_width = max(float(bbox[2] - bbox[0]), 1.0)
    original_text = entry.get("originalText", "")

    original_units = measure_text_units(original_text, font_profile)
    replacement_units = measure_text_units(replacement_text, font_profile)
    if original_units and replacement_units:
        return original_width * (replacement_units / original_units)

    original_len = max(len(normalize_text(original_text)), 1)
    replacement_len = max(len(normalize_text(replacement_text)), 1)
    return original_width * (replacement_len / original_len)


def measure_text_units(text: str, font_profile: dict[str, Any]) -> float | None:
    widths = font_profile.get("widths_by_char") or {}
    if not widths:
        return None
    total = 0.0
    for char in text:
        width = widths.get(char)
        if width is None:
            return None
        total += width
    return total



def shift_linked_currency_symbol(instructions: list[pikepdf.ContentStreamInstruction], page_entries: list[dict[str, Any]], source_entry: dict[str, Any], width_delta: float) -> None:
    if abs(width_delta) < 0.01:
        return

    source_bbox = source_entry.get("bbox") or [0, 0, 0, 0]
    for candidate in page_entries:
        if candidate.get("originalText") != "?":
            continue
        candidate_bbox = candidate.get("bbox") or [0, 0, 0, 0]
        same_line = abs(candidate_bbox[1] - source_bbox[1]) <= max(3.5, (source_entry.get("height") or 0) * 0.35)
        close_right = 0 <= (candidate_bbox[0] - source_bbox[2]) <= 18
        if not (same_line and close_right):
            continue

        tm_index = candidate.get("tmInstructionIndex")
        if tm_index is None or tm_index >= len(instructions):
            return

        tm_instruction = instructions[tm_index]
        if str(tm_instruction.operator) != "Tm":
            return

        operands = list(tm_instruction.operands)
        operands[4] = float(operands[4]) + float(width_delta)
        instructions[tm_index] = pikepdf.ContentStreamInstruction(operands, pikepdf.Operator("Tm"))
        return


def build_font_profiles(page: pikepdf.Page) -> dict[str, dict[str, Any]]:
    resources = page.obj.get("/Resources", pikepdf.Dictionary())
    fonts = resources.get("/Font", pikepdf.Dictionary())
    profiles = {}
    for font_key, font_obj in fonts.items():
        profiles[str(font_key)] = build_font_profile(font_obj)
    return profiles


def build_font_profile(font_obj: pikepdf.Object) -> dict[str, Any]:
    subtype = str(font_obj.get("/Subtype", ""))
    base_font = str(font_obj.get("/BaseFont", ""))
    code_to_unicode = parse_tounicode(font_obj.get("/ToUnicode")) if font_obj.get("/ToUnicode") else {}
    unicode_to_code = build_unicode_to_code_map(code_to_unicode)
    widths_by_char: dict[str, float] = {}

    if subtype in {"/Type1", "/TrueType"} and font_obj.get("/Widths") is not None:
        first_char = int(font_obj.get("/FirstChar", 0))
        widths = [float(value) for value in font_obj.get("/Widths", [])]
        for raw_code, value in code_to_unicode.items():
            if len(value) != 1 or len(raw_code) != 1:
                continue
            index = raw_code[0] - first_char
            if 0 <= index < len(widths):
                widths_by_char[value] = widths[index]
    elif subtype == "/Type0" and font_obj.get("/DescendantFonts"):
        descendant = font_obj["/DescendantFonts"][0]
        cid_widths = parse_cid_widths(descendant.get("/W", []), float(descendant.get("/DW", 1000)))
        default_width = float(descendant.get("/DW", 1000))
        for raw_code, value in code_to_unicode.items():
            if len(value) != 1:
                continue
            cid = int.from_bytes(raw_code, "big")
            widths_by_char[value] = cid_widths.get(cid, default_width)

    supported_chars = sorted(set(widths_by_char) | set(unicode_to_code))
    code_lengths = sorted({len(code) for code in code_to_unicode} or {1}, reverse=True)

    return {
        "subtype": subtype,
        "fontName": normalize_pdf_font_display(base_font),
        "supported_chars": supported_chars,
        "widths_by_char": widths_by_char,
        "code_to_unicode": code_to_unicode,
        "unicode_to_code": unicode_to_code,
        "code_lengths": code_lengths,
    }


def parse_tounicode(stream: pikepdf.Stream | None) -> dict[bytes, str]:
    if stream is None:
        return {}
    text = stream.read_bytes().decode("latin1")
    mapping: dict[bytes, str] = {}
    in_bfchar = False
    in_bfrange = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.endswith("beginbfchar"):
            in_bfchar = True
            continue
        if line == "endbfchar":
            in_bfchar = False
            continue
        if line.endswith("beginbfrange"):
            in_bfrange = True
            continue
        if line == "endbfrange":
            in_bfrange = False
            continue

        if in_bfchar:
            for src, dest in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", line):
                mapping[bytes.fromhex(src)] = decode_pdf_hex_text(dest)
        elif in_bfrange:
            match = re.match(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(.*)", line)
            if not match:
                continue
            start_code = int(match.group(1), 16)
            end_code = int(match.group(2), 16)
            source_hex_length = len(match.group(1))
            tail = match.group(3).strip()
            if tail.startswith("<"):
                base_hex = tail.strip("<>")
                base_value = int(base_hex or "0", 16)
                target_hex_length = max(len(base_hex), 4)
                for offset, code in enumerate(range(start_code, end_code + 1)):
                    mapping[bytes.fromhex(f"{code:0{source_hex_length}X}")] = decode_pdf_hex_text(f"{base_value + offset:0{target_hex_length}X}")
            elif tail.startswith("["):
                values = re.findall(r"<([0-9A-Fa-f]+)>", tail)
                for offset, code in enumerate(range(start_code, end_code + 1)):
                    if offset < len(values):
                        mapping[bytes.fromhex(f"{code:0{source_hex_length}X}")] = decode_pdf_hex_text(values[offset])

    return mapping


def decode_pdf_hex_text(value: str) -> str:
    raw = bytes.fromhex(value)
    if len(raw) >= 2 and len(raw) % 2 == 0:
        try:
            return raw.decode("utf-16-be")
        except UnicodeDecodeError:
            pass
    return raw.decode("latin1")


def parse_cid_widths(width_array: Any, default_width: float) -> dict[int, float]:
    widths: dict[int, float] = {}
    items = list(width_array)
    index = 0
    while index < len(items):
        start = int(items[index])
        next_item = items[index + 1]
        if isinstance(next_item, pikepdf.Array):
            for offset, width in enumerate(next_item):
                widths[start + offset] = float(width)
            index += 2
        else:
            end = int(next_item)
            width = float(items[index + 2]) if index + 2 < len(items) else default_width
            for code in range(start, end + 1):
                widths[code] = width
            index += 3
    return widths



def build_tf_instruction(font_key: str | None, font_size: float) -> pikepdf.ContentStreamInstruction:
    if not font_key:
        raise PdfEditError("Font anahtari bulunamadi.")
    return pikepdf.ContentStreamInstruction([pikepdf.Name(font_key), font_size], pikepdf.Operator("Tf"))


def encode_text_bytes(text: str, font_profile: dict[str, Any]) -> bytes:
    unicode_to_code: dict[str, bytes] = font_profile.get("unicode_to_code", {})
    if not unicode_to_code:
        return text.encode("latin1", errors="replace")

    parts = []
    for char in text:
        code = unicode_to_code.get(char)
        if code is None:
            raise PdfEditError(f"Desteklenmeyen karakter: {char}")
        parts.append(code)
    return b"".join(parts)


def insert_fallback_fonts(source_pdf_path: Path, output_pdf_path: Path, fallback_requests: dict[int, dict[str, dict[str, Any]]]) -> None:
    doc = fitz.open(source_pdf_path)
    try:
        for page_index, fonts in fallback_requests.items():
            page = doc[page_index]
            for external_font in fonts.values():
                page.insert_font(fontname=external_font["resource_key"].lstrip("/"), fontfile=str(external_font["path"]))
        doc.save(output_pdf_path)
    finally:
        doc.close()


def build_unicode_to_code_map(code_to_unicode: dict[bytes, str]) -> dict[str, bytes]:
    reverse: dict[str, bytes] = {}
    for raw_code, value in code_to_unicode.items():
        if len(value) != 1:
            continue
        existing = reverse.get(value)
        if existing is None or len(raw_code) < len(existing):
            reverse[value] = raw_code
    return reverse


def load_external_font_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    if not FALLBACK_FONT_ROOT.exists():
        return registry

    font_paths = sorted(FALLBACK_FONT_ROOT.rglob("*.otf")) + sorted(FALLBACK_FONT_ROOT.rglob("*.ttf"))
    for font_path in font_paths:
        font = fitz.Font(fontfile=str(font_path))
        display_name = font.name
        normalized_name = normalize_font_name(display_name)
        supported_chars = sorted(chr(codepoint) for codepoint in font.valid_codepoints() if codepoint >= 32)
        registry[normalized_name] = {
            "path": font_path,
            "display_name": display_name,
            "resource_key": f"/FEXT_{normalized_name.upper()}",
            "supported_chars": supported_chars,
        }
    return registry


def get_external_font_registry() -> dict[str, dict[str, Any]]:
    global _EXTERNAL_FONT_REGISTRY
    if _EXTERNAL_FONT_REGISTRY is None:
        _EXTERNAL_FONT_REGISTRY = load_external_font_registry()
    return _EXTERNAL_FONT_REGISTRY


def find_external_font_for_name(font_name: str | None) -> dict[str, Any] | None:
    if not font_name:
        return None
    return get_external_font_registry().get(normalize_font_name(font_name))


def choose_external_font(font_name: str | None, replacement_text: str) -> dict[str, Any] | None:
    registry = get_external_font_registry()
    if not registry:
        return None

    exact_match = find_external_font_for_name(font_name)
    if exact_match:
        exact_chars = set(exact_match.get("supported_chars", [])) | COMMON_EXTRA_CHARS
        if all(char in exact_chars for char in replacement_text):
            return exact_match

    requested_name = normalize_font_name(font_name)
    requested_tokens = extract_font_style_tokens(font_name)
    best_match: dict[str, Any] | None = None
    best_score: tuple[int, int, int, str] | None = None

    for key, external_font in registry.items():
        fallback_chars = set(external_font.get("supported_chars", [])) | COMMON_EXTRA_CHARS
        if not all(char in fallback_chars for char in replacement_text):
            continue

        candidate_tokens = extract_font_style_tokens(external_font.get("display_name"))
        score = (
            1 if requested_name and requested_name in key else 0,
            len(requested_tokens & candidate_tokens),
            1 if "regular" in candidate_tokens or "medium" in candidate_tokens else 0,
            key,
        )
        if best_score is None or score > best_score:
            best_match = external_font
            best_score = score

    return best_match


def normalize_font_name(value: str | None) -> str:
    if not value:
        return ""
    cleaned = str(value).strip().lstrip("/")
    if "+" in cleaned:
        cleaned = cleaned.split("+", 1)[1]
    return re.sub(r"[^a-z0-9]", "", cleaned.lower())


def extract_font_style_tokens(value: str | None) -> set[str]:
    normalized = normalize_font_name(value)
    tokens = set()
    for token in ("black", "extrabold", "bold", "semibold", "medium", "light", "extralight", "thin", "regular", "italic", "cond", "condensed"):
        if token in normalized:
            tokens.add(token)
    return tokens


def normalize_pdf_font_display(value: str | None) -> str:
    if not value:
        return ""
    cleaned = str(value).strip().lstrip("/")
    if "+" in cleaned:
        cleaned = cleaned.split("+", 1)[1]
    return cleaned


def plan_font_strategy(entry: dict[str, Any], replacement_text: str, original_profile: dict[str, Any]) -> dict[str, Any]:
    original_chars = set(original_profile.get("supported_chars", [])) | COMMON_EXTRA_CHARS
    missing_chars = sorted({char for char in replacement_text if char not in original_chars})
    if not missing_chars:
        return {"use_fallback": False, "resource_key": entry.get("fontKey"), "external_font": None}

    external_font = choose_external_font(entry.get("fontName") or original_profile.get("fontName"), replacement_text)
    if external_font:
        fallback_chars = set(external_font.get("supported_chars", [])) | COMMON_EXTRA_CHARS
        if all(char in fallback_chars for char in replacement_text):
            return {"use_fallback": True, "resource_key": external_font["resource_key"], "external_font": external_font}

    raise PdfEditError(f"{entry['id']} icin desteklenmeyen karakterler var: {' '.join(missing_chars)}")


def to_public_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "blockId": entry["blockId"],
        "pageNumber": entry["pageNumber"],
        "originalText": entry["originalText"],
        "replacementText": entry["replacementText"],
        "bbox": entry["bbox"],
        "width": entry.get("width"),
        "height": entry.get("height"),
        "fontKey": entry.get("fontKey"),
        "fontName": entry.get("fontName"),
        "fontSize": entry.get("fontSize"),
        "alignment": entry.get("alignment"),
        "editable": entry.get("editable"),
        "reason": entry.get("reason"),
        "widthBudget": entry.get("widthBudget"),
    }


def to_manifest_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["id"],
        "blockId": entry["blockId"],
        "pageNumber": entry["pageNumber"],
        "instructionIndex": entry["instructionIndex"],
        "tmInstructionIndex": entry.get("tmInstructionIndex"),
        "operator": entry["operator"],
        "fontKey": entry.get("fontKey"),
        "fontName": entry.get("fontName"),
        "fontSubtype": entry.get("fontSubtype"),
        "fontSize": entry.get("fontSize"),
        "resourceFontSize": entry.get("resourceFontSize"),
        "originalText": entry["originalText"],
        "bbox": entry.get("bbox"),
        "widthBudget": entry.get("widthBudget"),
        "alignment": entry.get("alignment"),
        "editable": entry.get("editable"),
        "reason": entry.get("reason"),
        "supportedChars": entry.get("supportedChars"),
        "segments": entry.get("segments"),
    }


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def round_float(value: float) -> float:
    return round(float(value), 3)


if __name__ == "__main__":
    sys.exit(main())







