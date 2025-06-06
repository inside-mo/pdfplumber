from flask import Flask, request, jsonify
  import pdfplumber

  app = Flask(name)

  @app.route("/extract", methods=["POST"])
  def extract_text():
    pdf_file = request.files.get("file")
    if not pdf_file:
      return jsonify({"error": "No file provided"}), 400
    with pdfplumber.open(pdf_file) as pdf:
      text = "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())
    return jsonify({"text": text})

  if name == "main":
    app.run(host="0.0.0.0", port=8765)
