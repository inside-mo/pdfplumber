import os
from flask import Flask, request, jsonify
import pdfplumber

app = Flask(name)

API_KEY = os.environ.get("API_KEY")
PORT = int(os.environ.get("PORT", 8765))

Health endpoint to verify the container is running
@app.route("/health", methods=["GET"])
def health():
return jsonify({"status": "ok"})

@app.route("/extract", methods=["POST"])
def extract_text():
if request.headers.get("x-api-key") != API_KEY:
return jsonify({"error": "Unauthorized"}), 401

pdf_file = request.files.get("file")
if not pdf_file:
return jsonify({"error": "No file provided"}), 400

try:
with pdfplumber.open(pdf_file) as pdf:
text = "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())
return jsonify({"text": text})
except Exception as e:
return jsonify({"error": str(e)}), 500
if name == "main":
app.run(host="0.0.0.0", port=PORT)
