import os
import json
import time
import webbrowser
from datetime import datetime
from threading import Timer

import requests
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from structured_output_service import build_structured_output
from review.review_service import save_review_log


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(BASE_DIR, ".env"))

UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
RESULT_DIR = os.path.join(BASE_DIR, "static", "results")

LOG_DIR = os.path.join(BASE_DIR, "logs")
RAW_JSON_DIR = os.path.join(LOG_DIR, "raw_json")
CLEAN_JSON_DIR = os.path.join(LOG_DIR, "clean_json")
TEXT_DIR = os.path.join(LOG_DIR, "text")
ERROR_DIR = os.path.join(LOG_DIR, "errors")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)
os.makedirs(RAW_JSON_DIR, exist_ok=True)
os.makedirs(CLEAN_JSON_DIR, exist_ok=True)
os.makedirs(TEXT_DIR, exist_ok=True)
os.makedirs(ERROR_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "tiff", "bmp"}

AZURE_ENDPOINT = os.getenv("AZURE_COMPUTER_VISION_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_COMPUTER_VISION_KEY")

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_logs(original_filename, raw_result, clean_result):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = secure_filename(original_filename).rsplit(".", 1)[0]

    raw_json_name = f"{timestamp}_{safe_name}_raw.json"
    clean_json_name = f"{timestamp}_{safe_name}_clean.json"
    text_log_name = f"{timestamp}_{safe_name}_text.txt"

    raw_json_path = os.path.join(RAW_JSON_DIR, raw_json_name)
    clean_json_path = os.path.join(CLEAN_JSON_DIR, clean_json_name)
    txt_log_path = os.path.join(TEXT_DIR, text_log_name)

    with open(raw_json_path, "w", encoding="utf-8") as f:
        json.dump(raw_result, f, indent=4, ensure_ascii=False)

    with open(clean_json_path, "w", encoding="utf-8") as f:
        json.dump(clean_result, f, indent=4, ensure_ascii=False)

    with open(txt_log_path, "w", encoding="utf-8") as f:
        f.write(clean_result.get("extracted_text", ""))

    return {
        "raw_json": raw_json_name,
        "clean_json": clean_json_name,
        "text_log": text_log_name,
    }


def call_computer_vision_ocr(file_path):
    if not AZURE_ENDPOINT or not AZURE_KEY:
        raise ValueError("Azure Computer Vision endpoint/key missing in OCR/.env file")

    read_url = AZURE_ENDPOINT.rstrip("/") + "/vision/v3.2/read/analyze"

    headers = {
        "Ocp-Apim-Subscription-Key": AZURE_KEY,
        "Content-Type": "application/octet-stream",
    }

    with open(file_path, "rb") as f:
        response = requests.post(read_url, headers=headers, data=f)

    if response.status_code != 202:
        raise Exception(f"Azure OCR submit failed: {response.status_code} - {response.text}")

    operation_url = response.headers.get("Operation-Location")

    if not operation_url:
        raise Exception("Azure OCR did not return Operation-Location header")

    for _ in range(30):
        result_response = requests.get(
            operation_url,
            headers={"Ocp-Apim-Subscription-Key": AZURE_KEY},
        )

        result_json = result_response.json()
        status = result_json.get("status")

        if status == "succeeded":
            return result_json

        if status == "failed":
            raise Exception(f"Azure OCR failed: {json.dumps(result_json, indent=2)}")

        time.sleep(1)

    raise TimeoutError("Azure OCR processing timed out")


def parse_computer_vision_result(result_json):
    extracted_text_lines = []
    pages = []

    analyze_result = result_json.get("analyzeResult", {})
    read_results = analyze_result.get("readResults", [])

    for page in read_results:
        page_data = {
            "page": page.get("page"),
            "angle": page.get("angle"),
            "width": page.get("width"),
            "height": page.get("height"),
            "unit": page.get("unit"),
            "line_count": len(page.get("lines", [])),
        }

        for line in page.get("lines", []):
            line_text = line.get("text", "")
            extracted_text_lines.append(line_text)

        pages.append(page_data)

    return {
        "ocr_engine": "Azure Computer Vision Read API v3.2",
        "status": result_json.get("status"),
        "total_pages": len(pages),
        "extracted_text": "\n".join(extracted_text_lines),
        "pages": pages,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_document():
    try:
        if "document" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["document"]

        if file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        if not allowed_file(file.filename):
            return jsonify({"error": "Invalid file type"}), 400

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = secure_filename(file.filename)
        saved_filename = f"{timestamp}_{original_filename}"
        file_path = os.path.join(UPLOAD_DIR, saved_filename)

        file.save(file_path)

        raw_result = call_computer_vision_ocr(file_path)
        clean_result = parse_computer_vision_result(raw_result)

        structured_output = build_structured_output(
            clean_result.get("extracted_text", "")
        )

        clean_result["structured_output"] = structured_output
        structured_dir = os.path.join(LOG_DIR, "structured")
        os.makedirs(structured_dir, exist_ok=True)

        structured_file = os.path.join(
            structured_dir,
            f"{timestamp}_{secure_filename(original_filename).rsplit('.',1)[0]}_structured.json"
        )

        with open(structured_file, "w", encoding="utf-8") as f:
            json.dump(structured_output, f, indent=4, ensure_ascii=False)
        clean_result["source_file"] = saved_filename
        clean_result["processed_at"] = datetime.now().isoformat()

        clean_result["log_files"] = save_logs(
            original_filename=original_filename,
            raw_result=raw_result,
            clean_result=clean_result,
        )

        return jsonify(clean_result)

    except Exception as e:
        error_data = {
            "error": str(e),
            "time": datetime.now().isoformat(),
        }

        error_file = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_error_log.json"
        error_path = os.path.join(ERROR_DIR, error_file)

        with open(error_path, "w", encoding="utf-8") as f:
            json.dump(error_data, f, indent=4)

        return jsonify(error_data), 500

@app.route("/review", methods=["POST"])
def review_document():
    try:
        review_data = request.get_json()

        if not review_data:
            return jsonify({"error": "No review data received"}), 400

        if "status" not in review_data:
            return jsonify({"error": "Review status is required"}), 400

        if review_data["status"] not in ["approved", "rejected", "edited"]:
            return jsonify({"error": "Invalid review status"}), 400

        saved_review = save_review_log(BASE_DIR, review_data)

        return jsonify({
            "message": "Review saved successfully",
            "review": saved_review
        })

    except Exception as e:
        return jsonify({
            "error": str(e),
            "time": datetime.now().isoformat()
        }), 500

def open_browser():
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    Timer(1, open_browser).start()
    app.run(debug=True, use_reloader=False)