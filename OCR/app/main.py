import os
import json
import time
import webbrowser
from datetime import datetime
from threading import Timer

import requests
from database import get_connection
from cashbank_service import insert_taruncashbank
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from structured_output_service import build_structured_output
from review.review_service import save_review_log
from auth_service import (
    get_all_divisions,
    get_year_codes,
    validate_user,
    create_user,
    get_division_details,
    increment_cpa_maxnumber
)

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

app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key")



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
def home():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    return render_template("dashboard.html")

@app.route("/extraction")
def extraction():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    return render_template("extraction.html")


@app.route("/validation")
def validation():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    return render_template("validation.html")


@app.route("/history")
def history():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    return render_template("history.html")


@app.route("/api/history", methods=["GET"])
def get_history():
    structured_dir = os.path.join(BASE_DIR, "logs", "structured")
    review_dir = os.path.join(BASE_DIR, "logs", "review")

    history = []

    os.makedirs(structured_dir, exist_ok=True)
    os.makedirs(review_dir, exist_ok=True)

    def get_file_time(path):
        try:
            return os.path.getmtime(path)
        except Exception:
            return time.time()

    def format_time(timestamp):
        try:
            return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %I:%M %p")
        except Exception:
            return ""

    def date_key(timestamp):
        try:
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
        except Exception:
            return ""

    def clean_amount_key(amount):
        try:
            if amount is None:
                return ""

            amount_text = str(amount).replace(",", "").strip()

            if not amount_text:
                return ""

            return str(float(amount_text))

        except Exception:
            return ""

    def get_cashbank_lookup_map():
        conn = None
        cursor = None
        lookup = {}

        try:
            divisioncode = session.get("divisioncode")
            yearcode = session.get("yearcode")

            if not divisioncode or not yearcode:
                return lookup

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT amount,
                       vocno,
                       accode,
                       ctcode
                FROM (
                    SELECT amount,
                           vocno,
                           accode,
                           ctcode,
                           id
                    FROM TARUNCASHBANK
                    WHERE divisioncode = :divisioncode
                      AND yearcode = :yearcode
                    ORDER BY id DESC
                )
                WHERE ROWNUM <= 1000
            """, {
                "divisioncode": int(divisioncode),
                "yearcode": int(yearcode)
            })

            for row in cursor.fetchall():
                amount_key = clean_amount_key(row[0])

                if amount_key and amount_key not in lookup:
                    lookup[amount_key] = {
                        "vocno": row[1],
                        "accode": row[2],
                        "ctcode": row[3]
                    }

            print("Cashbank history lookup loaded:", len(lookup))

            return lookup

        except Exception as e:
            print("Cashbank history lookup map error:", str(e))
            return lookup

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    cashbank_lookup_map = get_cashbank_lookup_map()
    reviewed_source_files = set()

    for filename in sorted(os.listdir(review_dir), reverse=True):
        if not filename.endswith(".json"):
            continue

        review_path = os.path.join(review_dir, filename)

        try:
            with open(review_path, "r", encoding="utf-8") as f:
                review_data = json.load(f)

            timestamp = get_file_time(review_path)

            source_file = review_data.get("source_file") or filename
            status = review_data.get("status", "pending")
            document_type = review_data.get("document_type", "unknown")
            corrected_fields = review_data.get("corrected_fields", {})

            reviewed_source_files.add(source_file)

            cashbank_result = review_data.get("cashbank_result") or {}

            if status == "approved" and not cashbank_result.get("vocno"):
                amount_key = clean_amount_key(corrected_fields.get("amount"))
                cashbank_lookup = cashbank_lookup_map.get(amount_key, {})

                if cashbank_lookup:
                    cashbank_result = {
                        "success": True,
                        "vocno": cashbank_lookup.get("vocno"),
                        "accode": cashbank_lookup.get("accode"),
                        "ctcode": cashbank_lookup.get("ctcode"),
                        "amount": corrected_fields.get("amount")
                    }

            activity = "Reviewed"

            if status == "approved":
                if cashbank_result.get("success"):
                    activity = "Approved & Inserted"
                else:
                    activity = "Approved"
            elif status == "rejected":
                activity = "Rejected"

            history.append({
                "time_display": format_time(timestamp),
                "date_key": date_key(timestamp),
                "sort_time": timestamp,
                "activity": activity,
                "source_file": source_file,
                "log_file": filename,
                "document_type": document_type,
                "status": status,
                "amount": corrected_fields.get("amount", ""),
                "account_head": corrected_fields.get("account_head", ""),
                "purpose": corrected_fields.get("purpose", ""),
                "reviewed_by": review_data.get("reviewed_by", ""),
                "fields": corrected_fields,
                "corrected_fields": corrected_fields,
                "vocno": cashbank_result.get("vocno", ""),
                "accode": cashbank_result.get("accode", ""),
                "ctcode": cashbank_result.get("ctcode", ""),
                "cashbank_result": cashbank_result
            })

        except Exception as e:
            print("History review log read error:", filename, str(e))

    for filename in sorted(os.listdir(structured_dir), reverse=True):
        if not filename.endswith(".json"):
            continue

        structured_path = os.path.join(structured_dir, filename)

        try:
            with open(structured_path, "r", encoding="utf-8") as f:
                structured_data = json.load(f)

            source_file = structured_data.get("source_file") or filename

            if source_file in reviewed_source_files:
                continue

            timestamp = get_file_time(structured_path)

            classification = structured_data.get("classification", {})
            fields = structured_data.get("fields", {})

            history.append({
                "time_display": format_time(timestamp),
                "date_key": date_key(timestamp),
                "sort_time": timestamp,
                "activity": "OCR Extracted / Pending Review",
                "source_file": source_file,
                "log_file": filename,
                "document_type": classification.get("document_type", "unknown"),
                "status": "pending",
                "amount": fields.get("amount", ""),
                "account_head": fields.get("account_head", ""),
                "purpose": fields.get("purpose", ""),
                "reviewed_by": "",
                "fields": fields,
                "corrected_fields": {},
                "vocno": "",
                "accode": "",
                "ctcode": "",
                "cashbank_result": {}
            })

        except Exception as e:
            print("History structured log read error:", filename, str(e))

    history.sort(
        key=lambda item: item.get("sort_time", 0),
        reverse=True
    )

    return jsonify(history)



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

        structured_output["source_file"] = saved_filename
        structured_output["file_url"] = f"/static/uploads/{saved_filename}"
        structured_output["processed_at"] = datetime.now().isoformat()

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

@app.route("/login", methods=["GET", "POST"])
def login():
    divisions = get_all_divisions()
    years = get_year_codes()

    if request.method == "GET":
        session.clear()
        return render_template(
            "login.html",
            divisions=divisions,
            years=years
        )

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()
    divisioncode = request.form.get("divisioncode", "").strip()
    yearcode = request.form.get("yearcode", "").strip()

    print("Login username:", username)
    print("Selected division code from login form:", divisioncode)
    print("Selected year code from login form:", yearcode)

    if not username or not password or not divisioncode or not yearcode:
        return render_template(
            "login.html",
            divisions=divisions,
            years=years,
            error="Username, password, department and year are required"
        )

    user_result = validate_user(username, password)
    print("User Code:", user_result.get("usercode"))
    print("User validation result:", user_result)

    if not user_result.get("valid"):
        return render_template(
            "login.html",
            divisions=divisions,
            years=years,
            error="Invalid username or password"
        )

    division = get_division_details(divisioncode)
    print("Division details from database:", division)

    if not division:
        return render_template(
            "login.html",
            divisions=divisions,
            years=years,
            error="Invalid department selected"
        )

    cpa_result = increment_cpa_maxnumber(divisioncode, yearcode)
    print("NOCONFIG CPA result:", cpa_result)

    if not cpa_result.get("success"):
        return render_template(
            "login.html",
            divisions=divisions,
            years=years,
            error=cpa_result.get("message", "Unable to update CPA number")
        )

    session["logged_in"] = True
    session["usercode"] = user_result["usercode"]
    session["username"] = username
    session["divisioncode"] = division["divisioncode"]
    session["divisiondesc"] = division["divdesc"]
    session["yearcode"] = yearcode
    session["voctype"] = "CPA"
    session["cpa_number"] = cpa_result.get("maxnumber")

    return redirect(url_for("dashboard"))


@app.route("/create-account", methods=["POST"])
def create_account():
    divisions = get_all_divisions()

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        return render_template(
            "login.html",
            divisions=divisions,
            error="Username and password are required"
        )

    result = create_user(username, password)

    if not result.get("success"):
        return render_template(
            "login.html",
            divisions=divisions,
            error=result.get("message")
        )

    return render_template(
        "login.html",
        divisions=divisions,
        success="Account created successfully. Please login."
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

    
@app.route("/review", methods=["POST"])
def review_document():
    try:
        review_data = request.get_json()

        print("\n" + "=" * 80)
        print("REVIEW REQUEST RECEIVED")
        print("=" * 80)

        if not review_data:
            return jsonify({
                "error": "No review data received"
            }), 400

        print("Review Data:")
        print(review_data)

        status = review_data.get("status")

        if not status:
            return jsonify({
                "error": "Review status is required"
            }), 400

        if status not in ["approved", "rejected", "edited"]:
            return jsonify({
                "error": "Invalid review status"
            }), 400

        saved_review = save_review_log(BASE_DIR, review_data)

        print("Review Log Saved")
        print(saved_review)

        cashbank_result = None

        if status == "approved":

            print("\nAPPROVE BUTTON CLICKED")

            session_data = {
                "cpa_number": session.get("cpa_number"),
                "usercode": session.get("usercode"),
                "divisioncode": session.get("divisioncode"),
                "yearcode": session.get("yearcode"),
                "username": session.get("username")
            }

            print("\nSession Data")
            print(session_data)

            voucher_fields = review_data.get(
                "corrected_fields",
                {}
            )

            print("\nVoucher Fields")
            print(voucher_fields)

            if not session_data["cpa_number"]:
                return jsonify({
                    "error": "CPA Number missing from session"
                }), 500

            if not session_data["usercode"]:
                return jsonify({
                    "error": "User Code missing from session"
                }), 500

            if not session_data["divisioncode"]:
                return jsonify({
                    "error": "Division Code missing from session"
                }), 500

            if not session_data["yearcode"]:
                return jsonify({
                    "error": "Year Code missing from session"
                }), 500

            print("\nCalling TARUNCASHBANK Insert")

            cashbank_result = insert_taruncashbank(
                voucher_fields=voucher_fields,
                session_data=session_data
            )

            print("\nInsert Result")
            print(cashbank_result)

            if not cashbank_result.get("success"):
                return jsonify({
                    "error": cashbank_result.get(
                        "message",
                        "Insert failed"
                    ),
                    "cashbank_result": cashbank_result
                }), 500

            print("\nTARUNCASHBANK INSERT SUCCESS")

        print("\nREVIEW COMPLETED")
        print("=" * 80)

        return jsonify({
            "success": True,
            "message": "Review saved successfully",
            "review": saved_review,
            "cashbank_result": cashbank_result
        })

    except Exception as e:

        print("\nREVIEW ERROR")
        print(str(e))

        return jsonify({
            "success": False,
            "error": str(e),
            "time": datetime.now().isoformat()
        }), 500

@app.route("/api/accounts", methods=["GET"])
def search_accounts():
    search_text = request.args.get("search", "").strip().upper()

    print("Account search request:", search_text)

    if not search_text:
        return jsonify([])

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ACCODE,
                   NAME
            FROM ACCOUNTS
            WHERE UPPER(NAME) LIKE '%' || :search_text || '%'
              AND ROWNUM <= 20
            ORDER BY NAME
        """, {
            "search_text": search_text
        })

        accounts = []

        for row in cursor.fetchall():
            accounts.append({
                "accode": str(row[0]),
                "name": str(row[1])
            })

        print("Accounts found:", accounts)

        return jsonify(accounts)

    except Exception as e:
        print("Account search error:", str(e))

        return jsonify({
            "error": str(e)
        }), 500

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


@app.route("/api/validation-documents", methods=["GET"])
def get_validation_documents():
    structured_dir = os.path.join(BASE_DIR, "logs", "structured")
    review_dir = os.path.join(BASE_DIR, "logs", "review")

    documents = []

    os.makedirs(structured_dir, exist_ok=True)
    os.makedirs(review_dir, exist_ok=True)

    # Read latest review status by source file
    review_status_map = {}

    for filename in os.listdir(review_dir):
        if not filename.endswith(".json"):
            continue

        review_path = os.path.join(review_dir, filename)

        try:
            with open(review_path, "r", encoding="utf-8") as f:
                review_data = json.load(f)

            source_file = review_data.get("source_file")
            status = review_data.get("status")

            if source_file:
                review_status_map[source_file] = status

        except Exception as e:
            print("Review log read error:", filename, str(e))

    # Read structured OCR documents
    for filename in os.listdir(structured_dir):
        if not filename.endswith(".json"):
            continue

        file_path = os.path.join(structured_dir, filename)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            source_file = data.get("source_file")
            file_url = data.get("file_url")

            classification = data.get("classification", {})
            fields = data.get("fields", {})
            validation = data.get("validation", {})

            review_status = review_status_map.get(source_file, "not_reviewed")

            # Hide approved documents
            if review_status == "approved":
                continue

            documents.append({
                "log_file": filename,
                "source_file": source_file,
                "file_url": file_url,
                "document_type": classification.get("document_type", "unknown"),
                "confidence": classification.get("confidence", "N/A"),
                "validation_status": review_status if review_status != "not_reviewed" else validation.get("status", "pending"),
                "review_status": review_status,
                "requires_review": validation.get("requires_review", True),
                "missing_fields": validation.get("missing_fields", []),
                "fields": fields
            })

        except Exception as e:
            print("Structured log read error:", filename, str(e))

    documents.sort(
        key=lambda item: item.get("log_file", ""),
        reverse=True
    )

    return jsonify(documents)


def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000/login")


if __name__ == "__main__":
    Timer(1, open_browser).start()
    app.run(debug=True, use_reloader=False)