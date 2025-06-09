from flask import Flask, request, jsonify
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
            word_texts = [w['text'].strip() for w in words]
            word_texts_lower = [w.lower() for w in word_texts]
            for target in targets:
                target_clean = target.strip().lower()
                target_words = [tw.strip() for tw in target_clean.split()]
                if len(target_words) == 1:
                    # Single word match: substring (handles phrases as a single extracted word)
                    for i, w in enumerate(word_texts_lower):
                        if target_words[0] in w:
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
                    # Multi-word: match if phrase appears as a single extracted word
                    joined_target = " ".join(target_words)
                    for i, w in enumerate(word_texts_lower):
                        if w == joined_target:
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
                    # Also, try to match as a sequence of separate words
                    for i in range(len(word_texts_lower) - len(target_words) + 1):
                        if word_texts_lower[i:i+len(target_words)] == target_words:
                            first = words[i]
                            last = words[i+len(target_words)-1]
                            found.append({
                                "page": page_num,
                                "text": " ".join(word_texts[i:i+len(target_words)]),
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
    print("Received words to redact:", words_to_redact)  # For debugging

    if not pdf_file:
        return jsonify({"error": "No file provided"}), 400
    if not words_to_redact:
        return jsonify({"error": "No words provided"}), 400

    temp_path = os.path.join('/tmp', f"pdfplumber_temp_{int(time.time())}.pdf")
    pdf_file.save(temp_path)
    try:
        results = locate_words(temp_path, words_to_redact)
        print("Locate words results:", results)  # For debugging
        os.remove(temp_path)
        return jsonify({"matches": results})
    except Exception as e:
        os.remove(temp_path)
        return jsonify({"error": str(e)}), 500

@app.route("/debug-words", methods=["POST"])
def debug_words():
    pdf_file = request.files.get("file")
    if not pdf_file:
        return jsonify({"error": "No file provided"}), 400
    temp_path = os.path.join('/tmp', f"debug_temp_{int(time.time())}.pdf")
    pdf_file.save(temp_path)
    output = []
    with pdfplumber.open(temp_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            words = page.extract_words(keep_blank_chars=True)
            output.append({
                "page": page_num,
                "words": [w['text'] for w in words]
            })
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
