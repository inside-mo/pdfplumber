import os
from flask import Flask, request, jsonify
import pdfplumber
import pandas as pd

# Create Flask app instance FIRST
app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
PORT = int(os.environ.get("PORT", 9546))

@app.route("/", methods=["GET"])
def root():
    return "OK", 200

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

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
            # Create a results object to hold redaction data
            results = []
            
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                lines = text.split('\n')
                
                for line in lines:
                    if field_name in line:
                        # Get text after the field name
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
    """Extract both text and tables from a PDF in a single request"""
    if request.headers.get("x-api-key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    
    pdf_file = request.files.get("file")
    if not pdf_file:
        return jsonify({"error": "No file provided"}), 400
    
    try:
        result = {
            "text": [],
            "tables": [],
            "combined": []
        }
        
        with pdfplumber.open(pdf_file) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # Safely extract text, replacing None with empty string
                text = page.extract_text() or ""
                result["text"].append({
                    "page": page_num,
                    "content": text
                })
                
                # Safely extract tables, replacing None with empty list
                tables = page.extract_tables() or []
                page_tables = []
                
                # Process each table
                for i, table in enumerate(tables, 1):
                    if not table:
                        continue
                        
                    # Convert to pandas DataFrame with explicit None handling
                    safe_table = [[cell or "" for cell in row] for row in table]
                    headers = safe_table[0] if safe_table else []
                    data = safe_table[1:] if len(safe_table) > 1 else []
                    
                    # Create a clean dataframe
                    df = pd.DataFrame(data, columns=headers)
                    
                    # Store table data
                    table_data = {
                        "table_number": i,
                        "headers": headers,
                        "data": df.to_dict(orient="records")
                    }
                    page_tables.append(table_data)
                
                # Add tables for this page
                if page_tables:
                    result["tables"].append({
                        "page": page_num,
                        "tables": page_tables
                    })
                
                # Create combined chronological elements
                elements = []
                
                # Add text as one element
                if text:
                    elements.append({
                        "type": "text",
                        "content": text
                    })
                
                # Add each table
                for i, table in enumerate(tables, 1):
                    if not table:
                        continue
                    
                    # Safe conversion to DataFrame with explicit None handling
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
                
                # Add the combined elements for this page
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
