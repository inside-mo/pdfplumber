import os
from flask import Flask, request, jsonify
import pdfplumber
import pandas as pd

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")
PORT = int(os.environ.get("PORT", 9546))

@app.route("/", methods=["GET"])
def root():
    return "OK", 200

@app.route("/health", methods=["GET"])
def health():
    return "OK", 200

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
            "text": [],        # Text content by page
            "tables": [],      # Table content by page
            "combined": []     # Chronological elements (text chunks and tables in order)
        }
        
        with pdfplumber.open(pdf_file) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # Extract all text from the page
                text = page.extract_text() or ""
                result["text"].append({
                    "page": page_num,
                    "content": text
                })
                
                # Extract tables
                tables = page.extract_tables()
                page_tables = []
                
                # Process each table
                for i, table in enumerate(tables, 1):
                    if not table:
                        continue
                        
                    # Convert to pandas DataFrame
                    headers = table[0] if table else []
                    data = table[1:] if len(table) > 1 else []
                    
                    # Create a clean dataframe
                    df = pd.DataFrame(data, columns=headers)
                    df = df.fillna("")
                    
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
                
                # For simplicity, add text as one element
                # In a more sophisticated implementation, you could split text
                # by position to accurately interleave with tables
                if text:
                    elements.append({
                        "type": "text",
                        "content": text
                    })
                
                # Add each table
                for i, table in enumerate(tables, 1):
                    if not table:
                        continue
                    
                    df = pd.DataFrame(table[1:], columns=table[0] if table else [])
                    elements.append({
                        "type": "table",
                        "table_number": i,
                        "headers": table[0] if table else [],
                        "data": df.fillna("").to_dict(orient="records")
                    })
                
                # Add the combined elements for this page
                result["combined"].append({
                    "page": page_num,
                    "elements": elements
                })
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Keep your existing endpoints
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
