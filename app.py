import os
import logging
from flask import Flask, request, jsonify
import pdfplumber

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
PORT = int(os.environ.get("PORT", 9546))

@app.route("/", methods=["GET"])
def root():
    return "OK", 200

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

@app.route("/test", methods=["POST"])
def test():
    """Endpoint to test POST requests without file handling"""
    logger.info("POST request received at /test")
    
    # Log headers
    logger.info(f"Headers: {dict(request.headers)}")
    
    # Check API key
    api_key = request.headers.get("x-api-key")
    logger.info(f"API key check: received={api_key}, expected={API_KEY}, match={api_key == API_KEY}")
    
    if api_key != API_KEY:
        logger.warning("API key authentication failed")
        return jsonify({"error": "Unauthorized"}), 401
    
    return jsonify({"status": "success", "message": "POST request processed successfully"}), 200

@app.route("/extract", methods=["POST"])
def extract_text():
    logger.info("POST request received at /extract")
    
    # Log headers
    logger.info(f"Headers: {dict(request.headers)}")
    
    # Check API key
    api_key = request.headers.get("x-api-key")
    logger.info(f"API key check: received={api_key}, expected={API_KEY}, match={api_key == API_KEY}")
    
    if api_key != API_KEY:
        logger.warning("API key authentication failed")
        return jsonify({"error": "Unauthorized"}), 401
    
    pdf_file = request.files.get("file")
    logger.info(f"PDF file received: {pdf_file is not None}")
    
    if not pdf_file:
        logger.warning("No file provided in the request")
        return jsonify({"error": "No file provided"}), 400
    
    try:
        logger.info("Processing PDF file...")
        with pdfplumber.open(pdf_file) as pdf:
            text = "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())
        logger.info(f"PDF processing successful, text length: {len(text)}")
        return jsonify({"text": text})
    except Exception as e:
        logger.error(f"Error processing PDF: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    logger.info(f"Starting app on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)
