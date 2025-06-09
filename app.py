from flask import Flask, request, jsonify, send_file
import os
import time
import pdfplumber

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
PORT = int(os.environ.get("PORT", 9546))

@app.route("/", methods=["GET"])
def root():
    return "OK", 200

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

def locate_words(pdf_path, targets):
    found = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words(keep_blank_chars=True)
            for target in targets:
                # For single-word targets, match individual words (case-insensitive)
                if len(target.split()) == 1:
                    for word in words:
                        if word['text'].strip().lower() == target.strip().lower():
                            found.append({
                                "page": page_num,
                                "text": word['text'],
                                "x0": float(word['x0']),
                                "y0": float(word['top']),
                                "x1": float(word['x1']),
                                "y1": float(word['bottom']),
                                "page_width": page.width,
                                "page_height": page.height
                            })
                else:
                    # For multi-word targets, try to match phrases on the same line
                    text_lines = (page.extract_text() or "").split('\n')
                    for line in text_lines:
                        if target.lower() in line.lower():
                            # Try to find first and last words of the phrase
                            phrase_words = target.strip().split()
                            i = 0
                            found_words = []
                            for w in words:
                                # Check if word matches next phrase word (case-insensitive)
                                if w['text'].strip().lower() == phrase_words[i].lower():
                                    found_words.append(w)
                                    i += 1
                                    if i == len(phrase_words):
                                        break
                                else:
                                    # Reset if the sequence breaks
                                    if found_words:
                                        found_words = []
                                        i = 0
                            if len(found_words) == len(phrase_words):
                                first = found_words[0]
                                last = found_words[-1]
                                found.append({
                                    "page": page_num,
                                    "text": target,
                                    "x0": float(first['x0']),
                                    "y0": float(first['top']),
                                    "x1": float(last['x1']),
                                    "y1": float(last['bottom']),
                                    "page_width": page.width,
                                    "page_height": page.height
                                })
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

    temp_path = os.path.join('/tmp', f"pdfplumber_temp_{int(time.time())}.pdf")
    pdf_file.save(temp_path)
    try:
        results = locate_words(temp_path, words_to_redact)
        os.remove(temp_path)
        return jsonify({"matches": results})
    except Exception as e:
        os.remove(temp_path)
        return jsonify({"error": str(e)}), 500

def locate_words(pdf_path, targets):
    found = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words(keep_blank_chars=True)
            word_texts = [w['text'].strip() for w in words]
            word_texts_lower = [w.lower() for w in word_texts]
            for target in targets:
                target_words = [tw.strip() for tw in target.split()]
                target_words_lower = [tw.lower() for tw in target_words]
                if len(target_words) == 1:
                    # Single word match
                    for i, w in enumerate(word_texts_lower):
                        if w == target_words_lower[0]:
                            word = words[i]
                            found.append({
                                "page": page_num,
                                "text": word['text'],
                                "x0": float(word['x0']),
                                "y0": float(word['top']),
                                "x1": float(word['x1']),
                                "y1": float(word['bottom']),
                                "page_width": page.width,
                                "page_height": page.height
                            })
                else:
                    # Multi-word sequence match
                    for i in range(len(word_texts_lower) - len(target_words_lower) + 1):
                        if word_texts_lower[i:i+len(target_words_lower)] == target_words_lower:
                            first = words[i]
                            last = words[i+len(target_words_lower)-1]
                            found.append({
                                "page": page_num,
                                "text": " ".join(word_texts[i:i+len(target_words_lower)]),
                                "x0": float(first['x0']),
                                "y0": float(first['top']),
                                "x1": float(last['x1']),
                                "y1": float(last['bottom']),
                                "page_width": page.width,
                                "page_height": page.height
                            })
    return found

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
                lines = text.split('\n')
                for line in lines:
                    if field_name in line:
                        parts = line.split(field_name, 1)
                        if len(parts) > 1:
                            value_to_redact = parts[1].strip()
                            results.append({
                                "page": page_num,
                                "field": field_name,
                                "value_detected": value_to_redact
                            })
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
        result = {
            "text": [],
            "tables": [],
            "combined": []
        }

        with pdfplumber.open(pdf_file) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                result["text"].append({
                    "page": page_num,
                    "content": text
                })
                tables = page.extract_tables() or []
                page_tables = []
                for i, table in enumerate(tables, 1):
                    if not table:
                        continue
                    safe_table = [[cell or "" for cell in row] for row in table]
                    headers = safe_table[0] if safe_table else []
                    data = safe_table[1:] if len(safe_table) > 1 else []
                    df = pd.DataFrame(data, columns=headers)
                    table_data = {
                        "table_number": i,
                        "headers": headers,
                        "data": df.to_dict(orient="records")
                    }
                    page_tables.append(table_data)
                if page_tables:
                    result["tables"].append({
                        "page": page_num,
                        "tables": page_tables
                    })
                elements = []
                if text:
                    elements.append({
                        "type": "text",
                        "content": text
                    })
                for i, table in enumerate(tables, 1):
                    if not table:
                        continue
                    safe_table = [[cell or "" for cell in row] for row in table]
                    headers = safe_table[0] if safe_table else []
                    data = safe_table[1:] if len(safe_table) > 1 else []
                    df = pd.DataFrame(data, columns=headers)
                    elements.append({
                        "type": "table",
                        "table_number": i,
                        "headers": headers,
                        "data": df.to_dict(orient="records")
                    })
                result["combined"].append({
                    "page": page_num,
                    "elements": elements
                })
        return jsonify(result)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
