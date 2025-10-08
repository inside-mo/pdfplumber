from flask import Flask, request, jsonify
import os
import time
import base64
import re
import pdfplumber

try:
    from pdfplumber.utils import extract_image
except ImportError:
    from pdfminer.pdftypes import resolve1
    from pdfminer.psparser import PSLiteral, PSKeyword

    def _literal_name(val):
        if isinstance(val, (PSLiteral, PSKeyword)):
            return val.name
        if isinstance(val, bytes):
            return val.decode("latin-1")
        return str(val)

    def _stream_filters(stream):
        filters = stream.attrs.get("Filter")
        if not filters:
            return []
        filters = resolve1(filters)
        if isinstance(filters, list):
            return [_literal_name(f) for f in filters]
        return [_literal_name(filters)]

    def extract_image(obj):
        stream = obj.get("stream")
        if stream is None:
            return {"image": None, "ext": None}
        stream = resolve1(stream)
        data = stream.get_data()
        filters = _stream_filters(stream)
        ext = "bin"
        for flt in filters:
            if flt == "DCTDecode":
                ext = "jpg"
                break
            if flt == "JPXDecode":
                ext = "jp2"
                break
            if flt in ("CCITTFaxDecode", "CCFDecode"):
                ext = "tiff"
                break
            if flt in ("FlateDecode", "LZWDecode"):
                ext = "png"
                break
        return {"image": data, "ext": ext}

app = Flask(__name__)
API_KEY = os.environ.get("API_KEY")
PORT = int(os.environ.get("PORT", 9546))


@app.route("/", methods=["GET"])
def root():
    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


@app.route("/extract-sitecheck-protocol", methods=["POST"])
def extract_sitecheck_protocol():
    if request.headers.get("x-api-key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    pdf_file = request.files.get("file")
    if not pdf_file:
        return jsonify({"error": "No file provided"}), 400

    try:
        result = {"document_header": {}, "site_info": {}, "sections": []}

        with pdfplumber.open(pdf_file) as pdf:
            if len(pdf.pages) > 0:
                first_page = pdf.pages[0]
                first_page_text = first_page.extract_text() or ""
                lines = first_page_text.split("\n")

                for line in lines[:10]:
                    line = line.strip()
                    doc_id_match = re.match(r"^(\d{6})\s*-\s*(.+)$", line)
                    if doc_id_match:
                        result["document_header"]["document_id"] = doc_id_match.group(1)
                        result["document_header"]["title"] = doc_id_match.group(2)
                    if "Deutsche Glasfaser" in line:
                        parts = line.split(" - ")
                        result["document_header"]["organization"] = parts[0].strip()
                        if len(parts) > 1:
                            result["document_header"]["note"] = parts[1].strip()

                field_patterns = [
                    (r"(\d{4,6})\s*\n\s*Standort\s*\*", "standort"),
                    (r"Record ID:\s*\*\s*\n\s*(\d+)", "record_id"),
                    (r"Datum:\s*\*\s*\n\s*(\d{2}\.\d{2}\.\d{4})", "datum"),
                    (r"POP \(Bundesland\):\s*\*\s*\n\s*([^\n]+)", "pop_bundesland"),
                    (r"POP ID:\s*\*\s*\n\s*([^\n]+)", "pop_id"),
                    (r"POP Typ:\s*\*\s*\n\s*([^\n]+)", "pop_typ"),
                    (r"USV-Typ:\s*\*\s*\n\s*([^\n]+)", "usv_typ"),
                ]

                for pattern, field_key in field_patterns:
                    match = re.search(pattern, first_page_text, re.IGNORECASE | re.MULTILINE)
                    if match:
                        result["site_info"][field_key] = match.group(1).strip()

                status_options = ["Wartung erfolgreich", "Kein Zugang", "Standort existiert nicht"]

                if hasattr(first_page, "annots") and first_page.annots:
                    for annot in first_page.annots:
                        if annot.get("data", {}).get("V"):
                            for option in status_options:
                                if option in str(annot.get("data", {})):
                                    result["site_info"]["status"] = option
                                    break

                if "status" not in result["site_info"]:
                    chars_df = first_page.chars
                    if chars_df is not None and len(chars_df) > 0:
                        chars = chars_df.to_dict("records") if hasattr(chars_df, "to_dict") else chars_df
                        for option in status_options:
                            option_words = first_page.search(option)
                            if option_words:
                                option_pos = option_words[0]
                                for char in chars:
                                    if (
                                        char.get("x0", 0) < option_pos["x0"] - 5
                                        and char.get("x0", 0) > option_pos["x0"] - 30
                                        and abs(char.get("top", 0) - option_pos["top"]) < 5
                                    ):
                                        if char.get("text", "") in ["✓", "X", "■", "●", "x", "✔", "✗"]:
                                            result["site_info"]["status"] = option
                                            break

                if "status" not in result["site_info"] and hasattr(first_page, "rects"):
                    for option in status_options:
                        option_words = first_page.search(option)
                        if option_words:
                            option_pos = option_words[0]
                            for rect in first_page.rects:
                                if (
                                    rect.get("x0", 0) < option_pos["x0"] - 5
                                    and rect.get("x0", 0) > option_pos["x0"] - 30
                                    and abs(rect.get("top", 0) - option_pos["top"]) < 10
                                    and rect.get("fill", False)
                                ):
                                    result["site_info"]["status"] = option
                                    break

            current_section = None
            current_subsection = None

            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                tables = page.extract_tables() or []
                lines = page_text.split("\n")

                for line_idx, line in enumerate(lines):
                    line = line.strip()

                    section_match = re.match(r"^(\d+)\.\s+(.+)$", line)
                    if section_match:
                        current_section = {
                            "number": section_match.group(1),
                            "title": section_match.group(2),
                            "subsections": [],
                            "page": page_num + 1,
                        }
                        result["sections"].append(current_section)
                        current_subsection = None
                        continue

                    subsection_match = re.match(r"^(\d+\.\d+)\s+(.+)$", line)
                    if subsection_match and current_section:
                        current_subsection = {
                            "number": subsection_match.group(1),
                            "title": subsection_match.group(2),
                            "items": [],
                            "page": page_num + 1,
                        }
                        current_section["subsections"].append(current_subsection)
                        continue

                    if re.match(r"^\d+\.jpg$", line, re.IGNORECASE):
                        if current_subsection:
                            current_subsection.setdefault("images", []).append(line)

                    if line.endswith("*") and current_subsection:
                        field_name = line.replace("*", "").strip()
                        if line_idx + 1 < len(lines):
                            value = lines[line_idx + 1].strip()
                            if value and not value.endswith("*"):
                                field_key = field_name.lower().replace(" ", "_").replace("-", "_")
                                current_subsection[field_key] = value

                    if "PoP Status" in line and current_subsection:
                        for i in range(line_idx + 1, min(line_idx + 3, len(lines))):
                            if i < len(lines) and ("Status 7" in lines[i] or "Status 9" in lines[i]):
                                status_line = lines[i]
                                if "✓" in status_line or "X" in status_line or "■" in status_line:
                                    if "Status 7" in status_line and any(
                                        marker in status_line.split("Status 7")[0] for marker in ["✓", "X", "■"]
                                    ):
                                        current_subsection["pop_status"] = "Status 7"
                                    elif "Status 9" in status_line and any(
                                        marker in status_line.split("Status 9")[0] for marker in ["✓", "X", "■"]
                                    ):
                                        current_subsection["pop_status"] = "Status 9"
                                else:
                                    status_7_pos = page.search("Status 7")
                                    status_9_pos = page.search("Status 9")
                                    if hasattr(page, "rects"):
                                        for rect in page.rects:
                                            if rect.get("fill", False):
                                                if status_7_pos and (
                                                    rect["x0"] < status_7_pos[0]["x0"] - 5
                                                    and rect["x0"] > status_7_pos[0]["x0"] - 30
                                                    and abs(rect["top"] - status_7_pos[0]["top"]) < 10
                                                ):
                                                    current_subsection["pop_status"] = "Status 7"
                                                elif status_9_pos and (
                                                    rect["x0"] < status_9_pos[0]["x0"] - 5
                                                    and rect["x0"] > status_9_pos[0]["x0"] - 30
                                                    and abs(rect["top"] - status_9_pos[0]["top"]) < 10
                                                ):
                                                    current_subsection["pop_status"] = "Status 9"
                                break

                    if "ZAS Schlüssel" in line and current_subsection:
                        zas_key = "zas_schluessel" if "2.4.2" in line else "zas_schluessel_vor_ort"
                        for i in range(line_idx + 1, min(line_idx + 4, len(lines))):
                            if i < len(lines):
                                option_line = lines[i]
                                if "Schlüssel" in option_line:
                                    if any(marker in option_line for marker in ["✓", "X", "■", "●"]):
                                        value = (
                                            option_line.replace("✓", "")
                                            .replace("X", "")
                                            .replace("■", "")
                                            .replace("●", "")
                                            .strip()
                                        )
                                        current_subsection[zas_key] = value
                                        break

                if current_subsection and tables:
                    for table in tables:
                        if not table or len(table) < 2:
                            continue
                        headers = table[0] if table else []
                        if any("OK" in str(h) and "Nicht OK" in str(h) for h in headers):
                            ok_col = nicht_ok_col = nicht_notwendig_col = None
                            for i, header in enumerate(headers):
                                header_str = str(header) if header else ""
                                if header_str == "OK":
                                    ok_col = i
                                elif "Nicht OK" in header_str:
                                    nicht_ok_col = i
                                elif "Nicht notwendig" in header_str or "notwendig" in header_str:
                                    nicht_notwendig_col = i

                            for row in table[1:]:
                                if len(row) < 2:
                                    continue
                                item_text = str(row[0]) if row[0] else ""
                                desc_text = str(row[1]) if len(row) > 1 and row[1] else ""
                                full_text = f"{item_text} {desc_text}".strip()
                                item_match = re.match(r"^(\d+\.\d+\.\d+)\s+(.+)$", full_text)
                                if item_match and item_match.group(1).startswith(current_subsection["number"] + "."):
                                    status = "Not checked"
                                    if ok_col is not None and len(row) > ok_col:
                                        cell_content = str(row[ok_col]).strip()
                                        if cell_content and cell_content not in ["", "OK", "-", " "]:
                                            status = "OK"
                                    if nicht_ok_col is not None and len(row) > nicht_ok_col:
                                        cell_content = str(row[nicht_ok_col]).strip()
                                        if cell_content and cell_content not in ["", "Nicht OK", "-", " "]:
                                            status = "Nicht OK"
                                    if nicht_notwendig_col is not None and len(row) > nicht_notwendig_col:
                                        cell_content = str(row[nicht_notwendig_col]).strip()
                                        if cell_content and cell_content not in ["", "Nicht notwendig", "notwendig", "-", " "]:
                                            status = "Nicht notwendig"
                                    full_row_text = " ".join(str(cell) for cell in row)
                                    if status == "Not checked":
                                        if any(marker in full_row_text for marker in ["✓", "X", "■", "●", "✔"]):
                                            for i, cell in enumerate(row):
                                                cell_str = str(cell)
                                                if any(marker in cell_str for marker in ["✓", "X", "■", "●", "✔"]):
                                                    if i == ok_col:
                                                        status = "OK"
                                                    elif i == nicht_ok_col:
                                                        status = "Nicht OK"
                                                    elif i == nicht_notwendig_col:
                                                        status = "Nicht notwendig"
                                                    break
                                    current_subsection["items"].append(
                                        {
                                            "number": item_match.group(1),
                                            "description": item_match.group(2).strip(),
                                            "status": status,
                                            "page": page_num + 1,
                                        }
                                    )

        return jsonify(result)
    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def locate_words(pdf_path, targets):
    found = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words(keep_blank_chars=True)
            word_texts = [w["text"].strip() for w in words]
            word_texts_lower = [w.lower() for w in word_texts]
            for target in targets:
                target_clean = target.strip().lower()
                target_words = [tw.strip() for tw in target_clean.split()]
                if len(target_words) == 1:
                    for i, w in enumerate(word_texts_lower):
                        if target_words[0] in w:
                            word = words[i]
                            found.append(
                                {
                                    "page": page_num,
                                    "text": word["text"],
                                    "x0": float(word["x0"]),
                                    "y0": float(word["top"]),
                                    "x1": float(word["x1"]),
                                    "y1": float(word["bottom"]),
                                    "page_width": page.width,
                                    "page_height": page.height,
                                }
                            )
                else:
                    joined_target = " ".join(target_words)
                    for i, w in enumerate(word_texts_lower):
                        if w == joined_target:
                            word = words[i]
                            found.append(
                                {
                                    "page": page_num,
                                    "text": word["text"],
                                    "x0": float(word["x0"]),
                                    "y0": float(word["top"]),
                                    "x1": float(word["x1"]),
                                    "y1": float(word["bottom"]),
                                    "page_width": page.width,
                                    "page_height": page.height,
                                }
                            )
                    for i in range(len(word_texts_lower) - len(target_words) + 1):
                        if word_texts_lower[i : i + len(target_words)] == target_words:
                            first = words[i]
                            last = words[i + len(target_words) - 1]
                            found.append(
                                {
                                    "page": page_num,
                                    "text": " ".join(word_texts[i : i + len(target_words)]),
                                    "x0": float(first["x0"]),
                                    "y0": float(first["top"]),
                                    "x1": float(last["x1"]),
                                    "y1": float(last["bottom"]),
                                    "page_width": page.width,
                                    "page_height": page.height,
                                }
                            )
    return found


@app.route("/locate-words", methods=["POST"])
def locate_words_endpoint():
    if request.headers.get("x-api-key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    pdf_file = request.files.get("file")
    words_to_redact = request.form.getlist("words")
    if not pdf_file:
        return jsonify({"error": "No file provided"}), 400
    if not words_to_redact:
        return jsonify({"error": "No words provided"}), 400
    temp_path = os.path.join("/tmp", f"pdfplumber_temp_{int(time.time())}.pdf")
    pdf_file.save(temp_path)
    try:
        results = locate_words(temp_path, words_to_redact)
        os.remove(temp_path)
        return jsonify({"locations": results})
    except Exception as e:
        os.remove(temp_path)
        return jsonify({"error": str(e)}), 500


@app.route("/debug-words", methods=["POST"])
def debug_words():
    pdf_file = request.files.get("file")
    if not pdf_file:
        return jsonify({"error": "No file provided"}), 400
    temp_path = os.path.join("/tmp", f"debug_temp_{int(time.time())}.pdf")
    pdf_file.save(temp_path)
    output = []
    with pdfplumber.open(temp_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words(keep_blank_chars=True)
            output.append({"page": page_num, "words": [w["text"] for w in words]})
    os.remove(temp_path)
    return jsonify(output)


@app.route("/redact", methods=["POST"])
def redact_text():
    if request.headers.get("x-api-key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    pdf_file = request.files.get("file")
    field_name = request.form.get("fieldName")
    if not pdf_file:
        return jsonify({"error": "No file provided"}), 400
    if not field_name:
        return jsonify({"error": "No field name provided"}), 400
    try:
        with pdfplumber.open(pdf_file) as pdf:
            results = []
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                lines = text.split("\n")
                for line in lines:
                    if field_name in line:
                        parts = line.split(field_name, 1)
                        if len(parts) > 1:
                            value_to_redact = parts[1].strip()
                            results.append({"page": page_num, "field": field_name, "value_detected": value_to_redact})
            return jsonify({"redaction_targets": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/extract", methods=["POST"])
def extract_text():
    if request.headers.get("x-api-key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    pdf_file = request.files.get("file")
    if not pdf_file:
        return jsonify({"error": "No file provided"}), 400
    try:
        with pdfplumber.open(pdf_file) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/extract-all", methods=["POST"])
def extract_all():
    if request.headers.get("x-api-key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    pdf_file = request.files.get("file")
    if not pdf_file:
        return jsonify({"error": "No file provided"}), 400
    try:
        import pandas as pd

        result = {"text": [], "tables": [], "combined": []}
        with pdfplumber.open(pdf_file) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                result["text"].append({"page": page_num, "content": text})
                tables = page.extract_tables() or []
                page_tables = []
                for i, table in enumerate(tables, 1):
                    if not table:
                        continue
                    safe_table = [[cell or "" for cell in row] for row in table]
                    headers = safe_table[0] if safe_table else []
                    data = safe_table[1:] if len(safe_table) > 1 else []
                    df = pd.DataFrame(data, columns=headers)
                    table_data = {"table_number": i, "headers": headers, "data": df.to_dict(orient="records")}
                    page_tables.append(table_data)
                if page_tables:
                    result["tables"].append({"page": page_num, "tables": page_tables})
                elements = []
                if text:
                    elements.append({"type": "text", "content": text})
                for i, table in enumerate(tables, 1):
                    if not table:
                        continue
                    safe_table = [[cell or "" for cell in row] for row in table]
                    headers = safe_table[0] if safe_table else []
                    data = safe_table[1:] if len(safe_table) > 1 else []
                    df = pd.DataFrame(data, columns=headers)
                    elements.append(
                        {"type": "table", "table_number": i, "headers": headers, "data": df.to_dict(orient="records")}
                    )
                result["combined"].append({"page": page_num, "elements": elements})
        return jsonify(result)
    except Exception as e:
        import traceback

        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/extract-images", methods=["POST"])
def extract_images():
    if request.headers.get("x-api-key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    pdf_file = request.files.get("file")
    if not pdf_file:
        return jsonify({"error": "No file provided"}), 400

    try:
        images_out = []
        with pdfplumber.open(pdf_file) as pdf:
            seen = set()
            for page_num, page in enumerate(pdf.pages, 1):
                raw_image_objs = getattr(page, "objects", None)

                if raw_image_objs and hasattr(raw_image_objs, "get"):
                    image_objects = raw_image_objs.get("image", {}) or {}
                else:
                    candidates = raw_image_objs if isinstance(raw_image_objs, list) else []
                    image_objects = {
                        obj.get("name"): obj
                        for obj in candidates
                        if isinstance(obj, dict)
                        and obj.get("object_type") == "image"
                        and obj.get("name")
                    }

                for img in page.images:
                    name = img.get("name")
                    if not name or name in seen:
                        continue
                    seen.add(name)

                    obj = image_objects.get(name)
                    if not obj:
                        continue

                    extracted = extract_image(obj)
                    img_bytes = extracted.get("image")
                    if not img_bytes:
                        continue

                    img_ext = extracted.get("ext") or "bin"
                    images_out.append(
                        {
                            "page": page_num,
                            "name": name,
                            "ext": img_ext,
                            "data_base64": base64.b64encode(img_bytes).decode("utf-8"),
                        }
                    )
        return jsonify({"images": images_out})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
