import os
import glob
import subprocess
import json
import re
import time
import webbrowser
from datetime import datetime
from threading import Timer

import requests
from database import get_connection
from cashbank_service import insert_taruncashbank
from cash_voucher_entry_service import insert_cash_voucher_entry, list_cash_voucher_entries, get_cash_voucher_entry_by_id, update_cash_voucher_entry, list_petty_cash_accounts, is_ia_auth_user, authenticate_cash_voucher_entry
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





@app.route("/ia-authentication")
def ia_authentication():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    usercode = session.get("usercode")
    if not is_ia_auth_user(usercode):
        return redirect(url_for("dashboard"))

    return render_template("ia_authentication.html")


@app.route("/api/ia-authentication/print/<int:voucher_id>", methods=["POST"])
def ia_authentication_print(voucher_id):
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    usercode = session.get("usercode")
    if not is_ia_auth_user(usercode):
        return jsonify({
            "success": False,
            "message": "Only IA authentication user can authenticate voucher"
        }), 403

    result = authenticate_cash_voucher_entry(voucher_id, usercode)
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/ia-authentication/update/<int:voucher_id>", methods=["POST"])
def ia_authentication_update(voucher_id):
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    usercode = session.get("usercode")

    if not is_ia_auth_user(usercode):
        return jsonify({
            "success": False,
            "message": "Only IA authentication user can update voucher"
        }), 403

    data = request.get_json() or {}

    # IA does not edit these fields directly.
    # Preserve the existing voucher values rather than clearing them.
    current_result = get_cash_voucher_entry_by_id(voucher_id)

    if not current_result.get("success"):
        return jsonify({
            "success": False,
            "message": "Voucher not found"
        }), 404

    current = (
        current_result.get("voucher")
        or current_result.get("entry")
        or current_result.get("row")
        or {}
    )

    if not data.get("account_name"):
        data["account_name"] = current.get("account_name") or ""

    if not data.get("account_head_code"):
        data["account_head_code"] = (
            current.get("account_head_code") or ""
        )

    # IA edit modal does not expose these optional fields.
    # Never erase them during an IA edit.
    data["invoice_no"] = current.get("invoice_no") or ""
    data["invoice_date"] = current.get("invoice_date") or ""
    data["party_code"] = current.get("party_code") or ""
    data["party_name"] = current.get("party_name") or ""

    # IA edit does not edit On Duty records.
    # Preserve all existing On Duty information.
    data["on_duty_details"] = (
        current.get("on_duty_details") or []
    )

    result = update_cash_voucher_entry(
        voucher_id,
        data,
        usercode=usercode,
        allow_any_user=True
    )

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/voucher-draft")
def voucher_draft():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    return render_template("voucher_draft.html")



@app.route("/api/cash-voucher-entry/accounts", methods=["GET"])
def cash_voucher_entry_accounts():
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required",
            "rows": []
        }), 401

    account_type = (request.args.get("type") or "others").strip().lower()


    result = list_petty_cash_accounts(account_type=account_type)
    return jsonify(result)



@app.route("/api/cash-voucher-entry/parties")
def cash_voucher_entry_parties():
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    search = (request.args.get("search") or "").strip()

    if len(search) < 2:
        return jsonify({
            "success": True,
            "parties": []
        })

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM (
                SELECT PARTYCODE, PARTYNAME
                FROM SCM.PARTYMASTER
                WHERE PARTYNAME IS NOT NULL
                  AND UPPER(PARTYNAME) LIKE '%' || UPPER(:search) || '%'
                ORDER BY PARTYNAME
            )
            WHERE ROWNUM <= 25
        """, {
            "search": search
        })

        parties = []
        for row in cursor.fetchall():
            parties.append({
                "party_code": str(row[0] or ""),
                "party_name": str(row[1] or "")
            })

        return jsonify({
            "success": True,
            "parties": parties
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


@app.route("/api/cash-voucher-entry/on-duty-users")
def cash_voucher_entry_on_duty_users():
    if not session.get("logged_in"):
        return jsonify({"success": False, "message": "Login required", "rows": [], "count": 0}), 401

    date_raw = (request.args.get("date") or "").strip()

    if not date_raw:
        return jsonify({"success": True, "rows": [], "count": 0})

    # convert YYYY-MM-DD to YYYYMMDD as required by query
    selected_date = date_raw.replace('-', '')

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT r.Usercode,
                   d.Empcode,
                   d.Outdate,
                   r.UserName,
                   TO_CHAR(d.OutTime, 'YYYY-MM-DD HH24:MI') AS OutTime,
                   TO_CHAR(d.InTime, 'YYYY-MM-DD HH24:MI') AS InTime,
                   odr.OndutyReason AS OndutyReason,
                   d.Remarks AS Remarks
            FROM HRDNEW.DEPTONDUTYDETAILS d
            INNER JOIN SCM.RAWUSER r
                ON r.Empcode = d.Empcode
            LEFT JOIN HRDNEW.REASONFORONDUTY odr
                ON odr.OndutyReasonCode = d.PurposeCode
            WHERE d.Outdate >= :selected_date
              AND d.Outdate <= :selected_date
            ORDER BY r.UserName
        """, {"selected_date": selected_date})

        rows = []
        for row in cursor.fetchall():
            rows.append({
                "usercode": str(row[0] or ""),
                "empcode": str(row[1] or ""),
                "outdate": str(row[2] or ""),
                "username": str(row[3] or ""),
                "outtime": str(row[4] or ""),
                "intime": str(row[5] or ""),
                "reason": str(row[6] or ""),
                "remarks": str(row[7] or "")
            })

        return jsonify({"success": True, "rows": rows, "count": len(rows)})

    except Exception as e:
        return jsonify({"success": False, "message": str(e), "rows": [], "count": 0}), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

@app.route("/api/cash-voucher-entry/save", methods=["POST"])
def save_cash_voucher_entry():
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    try:
        data = request.get_json() or {}

        result = insert_cash_voucher_entry(
            data,
            session,
            entry_source=data.get("entry_source") or "MANUAL"
        )

        return jsonify(result), 200 if result.get("success") else 400

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


@app.route("/api/cash-voucher-entry/list", methods=["GET"])
def cash_voucher_entry_list_api():
    if not session.get("logged_in"):
        return jsonify({"success": False, "message": "Login required", "rows": [], "entries": []}), 401

    try:
        limit_raw = request.args.get("limit", "1000")

        if str(limit_raw).lower() == "all":
            limit = 5000
        else:
            limit = int(limit_raw or 1000)

        limit = max(1, min(limit, 5000))

        result = list_cash_voucher_entries(limit=limit)

        entries = result.get("entries") or result.get("rows") or []
        result["entries"] = entries
        result["rows"] = entries

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
            "rows": [],
            "entries": []
        }), 500


@app.route("/api/cash-voucher-entry/get/<int:voucher_id>", methods=["GET"])
def get_cash_voucher_entry(voucher_id):
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    result = get_cash_voucher_entry_by_id(voucher_id)
    status_code = 200 if result.get("success") else 404
    return jsonify(result), status_code


@app.route("/api/cash-voucher-entry/update/<int:voucher_id>", methods=["POST"])
def update_cash_voucher_entry_route(voucher_id):
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    data = request.get_json() or {}

    result = update_cash_voucher_entry(
        voucher_id,
        data,
        usercode=session.get("usercode"),
        allow_any_user=False
    )

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/cash-voucher-entry")
def cash_voucher_entry():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    return render_template("cash_voucher_entry.html")


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
                "source_file": safe_source_file,
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
                "source_file": safe_source_file,
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






@app.route("/api/ocr-extraction/approve", methods=["POST"])
def approve_ocr_extraction():
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required"
        }), 401

    conn = None
    cursor = None

    try:
        data = request.get_json() or {}

        account_name = (data.get("account_name") or "").strip().upper()
        account_head_code = (data.get("account_head_code") or "").strip()

        if account_name and not account_head_code:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT accode
                FROM accounts
                WHERE pettycashflag = 1
                  AND UPPER(TRIM(name)) = :account_name
            """, {
                "account_name": account_name
            })

            row = cursor.fetchone()

            if row:
                account_head_code = row[0]

            cursor.close()
            conn.close()
            cursor = None
            conn = None

        save_data = {
            "voucherdate": data.get("voucherdate"),
            "account_head_code": account_head_code,
            "account_name": account_name,
            "person_name": data.get("person_name"),
            "purpose": data.get("purpose"),
            "amount": data.get("amount")
        }

        result = insert_cash_voucher_entry(
            save_data,
            session,
            entry_source="OCR"
        )

        if not result.get("success"):
            return jsonify(result), 400

        return jsonify({
            "success": True,
            "message": "OCR voucher approved and inserted successfully",
            "voucher_id": result.get("id") or result.get("voucher_id"),
            "account_head_code": account_head_code,
            "account_name": account_name
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()




@app.route("/api/scanned-documents", methods=["GET"])
def scanned_documents():
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required",
            "rows": []
        }), 401

    try:
        upload_dir = os.path.abspath(os.path.join(app.root_path, "..", "static", "uploads"))
        os.makedirs(upload_dir, exist_ok=True)

        files = []
        for path in glob.glob(os.path.join(upload_dir, "scan_*.png")):
            filename = os.path.basename(path)
            stat = os.stat(path)

            files.append({
                "filename": filename,
                "file_url": url_for("static", filename=f"uploads/{filename}"),
                "size": stat.st_size,
                "modified": stat.st_mtime
            })

        files.sort(key=lambda x: x["modified"], reverse=True)

        return jsonify({
            "success": True,
            "rows": files[:50]
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
            "rows": []
        }), 500



@app.route("/api/scan-document", methods=["POST"])
def scan_document():
    if not session.get("logged_in"):
        return jsonify({"success": False, "message": "Login required"}), 401

    try:
        import subprocess
        from datetime import datetime

        scan_dir = os.path.join(BASE_DIR, "static", "uploads")
        os.makedirs(scan_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"scan_{timestamp}.png"
        output_path = os.path.join(scan_dir, output_filename)

        command = [
            "scanimage",
            "-d", "escl:http://localhost:60000",
            "--source", "ADF",
            "--format=png",
            "--mode", "Gray",
            "--resolution", "200",
            "-x", "148",
            "-y", "210",
        ]

        with open(output_path, "wb") as out_file:
            result = subprocess.run(
                command,
                stdout=out_file,
                stderr=subprocess.PIPE,
                text=False,
                timeout=180,
            )

        if result.returncode != 0:
            try:
                os.remove(output_path)
            except Exception:
                pass

            error_text = ""
            try:
                error_text = result.stderr.decode("utf-8", errors="ignore")
            except Exception:
                error_text = str(result.stderr)

            return jsonify({
                "success": False,
                "message": "Scan failed",
                "error": error_text,
                "command": " ".join(command),
            }), 500

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return jsonify({
                "success": False,
                "message": "Scanner completed but PNG file was not created",
            }), 500

        file_url = url_for("static", filename=f"uploads/{output_filename}")

        return jsonify({
            "success": True,
            "message": "Document scanned successfully",
            "filename": output_filename,
            "file_url": file_url,
            "file_path": output_path,
        })

    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "message": "Scanner timeout. Check ADF paper and try again."
        }), 500

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        }), 500


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

    if int(session.get("usercode") or 0) == 2008:
        return redirect(url_for("ia_authentication"))

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
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required",
            "documents": []
        }), 401

    try:
        structured_dir = os.path.join(BASE_DIR, "logs", "structured")
        review_dir = os.path.join(BASE_DIR, "logs", "review")

        documents = []

        if not os.path.exists(structured_dir):
            return jsonify({
                "success": True,
                "documents": []
            })

        for filename in sorted(os.listdir(structured_dir), reverse=True):
            if not filename.lower().endswith(".json"):
                continue

            structured_path = os.path.join(structured_dir, filename)

            try:
                with open(structured_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    continue

                base_name = (
                    filename
                    .replace("_structured.json", "")
                    .replace(".json", "")
                )

                source_file = (
                    data.get("source_file")
                    or data.get("filename")
                    or data.get("original_filename")
                    or data.get("source_filename")
                    or data.get("document_name")
                    or base_name
                )

                if str(source_file).lower() in ("unknown", "unknown document", "none", "null", ""):
                    source_file = base_name

                validation = data.get("validation") or {}

                review_file = filename.replace("_structured.json", "_review.json")
                review_path = os.path.join(review_dir, review_file)

                review_data = {}
                review_status = "not_reviewed"

                if os.path.exists(review_path):
                    try:
                        with open(review_path, "r", encoding="utf-8") as rf:
                            review_data = json.load(rf)
                        review_status = review_data.get("status") or review_data.get("review_status") or "reviewed"
                    except Exception:
                        review_status = "reviewed"

                documents.append({
                    "source_file": source_file,
                    "filename": source_file,
                    "log_file": filename,
                    "structured_file": filename,
                    "review_file": review_file if os.path.exists(review_path) else "",
                    "document_type": data.get("document_type") or data.get("type") or "Extracted",
                    "validation_status": review_status if review_status != "not_reviewed" else validation.get("status", "needs_review"),
                    "requires_review": validation.get("requires_review", True),
                    "missing_fields": validation.get("missing_fields", []),
                    "warnings": validation.get("warnings", []),
                    "errors": validation.get("errors", []),
                    "data": data,
                    "review": review_data
                })

            except Exception as e:
                print("Validation document read error:", filename, str(e))
                continue

        return jsonify({
            "success": True,
            "documents": documents
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
            "documents": []
        }), 500


@app.route("/api/dashboard", methods=["GET"])
def get_dashboard():
    structured_dir = os.path.join(BASE_DIR, "logs", "structured")
    review_dir = os.path.join(BASE_DIR, "logs", "review")

    os.makedirs(structured_dir, exist_ok=True)
    os.makedirs(review_dir, exist_ok=True)

    total_documents = 0
    approved_count = 0
    rejected_count = 0
    pending_count = 0
    approved_amount = 0.0

    reviewed_source_files = set()
    daily_map = {}
    recent_activity = []

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

    def clean_amount(value):
        try:
            if value is None:
                return 0.0

            text = str(value).replace(",", "").strip()

            if not text:
                return 0.0

            match = re.search(r"\d+(\.\d+)?", text)

            if not match:
                return 0.0

            return float(match.group())

        except Exception:
            return 0.0

    def ensure_day(day):
        if day not in daily_map:
            daily_map[day] = {
                "date": day,
                "pending": 0,
                "approved": 0,
                "rejected": 0,
                "total": 0
            }

    # Reviewed documents: approved / rejected
    for filename in sorted(os.listdir(review_dir), reverse=True):
        if not filename.endswith(".json"):
            continue

        review_path = os.path.join(review_dir, filename)

        try:
            with open(review_path, "r", encoding="utf-8") as f:
                review_data = json.load(f)

            timestamp = get_file_time(review_path)
            day = date_key(timestamp)

            source_file = review_data.get("source_file") or filename
            status = review_data.get("status", "pending")
            document_type = review_data.get("document_type", "unknown")
            corrected_fields = review_data.get("corrected_fields", {})

            reviewed_source_files.add(source_file)
            ensure_day(day)

            activity = "Reviewed"

            if status == "approved":
                approved_count += 1
                daily_map[day]["approved"] += 1
                activity = "Approved"
                approved_amount += clean_amount(corrected_fields.get("amount"))

                cashbank_result = review_data.get("cashbank_result") or {}
                if cashbank_result.get("success"):
                    activity = "Approved & Inserted"

            elif status == "rejected":
                rejected_count += 1
                daily_map[day]["rejected"] += 1
                activity = "Rejected"

            else:
                pending_count += 1
                daily_map[day]["pending"] += 1
                activity = "Pending Review"

            daily_map[day]["total"] += 1

            recent_activity.append({
                "sort_time": timestamp,
                "time_display": format_time(timestamp),
                "activity": activity,
                "source_file": safe_source_file,
                "document_type": document_type,
                "status": status,
                "amount": corrected_fields.get("amount", "")
            })

        except Exception as e:
            print("Dashboard review log error:", filename, str(e))

    # Structured documents: pending documents
    for filename in sorted(os.listdir(structured_dir), reverse=True):
        if not filename.endswith(".json"):
            continue

        structured_path = os.path.join(structured_dir, filename)

        try:
            with open(structured_path, "r", encoding="utf-8") as f:
                structured_data = json.load(f)

            source_file = structured_data.get("source_file") or filename

            total_documents += 1

            if source_file in reviewed_source_files:
                continue

            timestamp = get_file_time(structured_path)
            day = date_key(timestamp)

            classification = structured_data.get("classification", {})
            fields = structured_data.get("fields", {})

            pending_count += 1
            ensure_day(day)

            daily_map[day]["pending"] += 1
            daily_map[day]["total"] += 1

            recent_activity.append({
                "sort_time": timestamp,
                "time_display": format_time(timestamp),
                "activity": "OCR Extracted / Pending Review",
                "source_file": safe_source_file,
                "document_type": classification.get("document_type", "unknown"),
                "status": "pending",
                "amount": fields.get("amount", "")
            })

        except Exception as e:
            print("Dashboard structured log error:", filename, str(e))

    recent_activity.sort(
        key=lambda item: item.get("sort_time", 0),
        reverse=True
    )

    daily_trend = list(daily_map.values())
    daily_trend.sort(key=lambda item: item.get("date", ""))

    return jsonify({
        "summary": {
            "total_documents": total_documents,
            "pending": pending_count,
            "approved": approved_count,
            "rejected": rejected_count,
            "approved_amount": approved_amount
        },
        "daily_trend": daily_trend[-10:],
        "recent_activity": recent_activity[:8],
        "status_breakdown": {
            "pending": pending_count,
            "approved": approved_count,
            "rejected": rejected_count
        }
    })

def open_browser():
    webbrowser.open_new("http://127.0.0.1:5000/login")



@app.route("/api/cash-voucher-entry/purpose-suggestions", methods=["GET"])
def cash_voucher_purpose_suggestions():
    if not session.get("logged_in"):
        return jsonify({"success": False, "message": "Login required", "purposes": []}), 401

    connection = None
    try:
        usercode = session.get("usercode")
        if not usercode:
            return jsonify({"success": True, "purposes": []})

        connection = get_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT PURPOSE
                FROM (
                    SELECT PURPOSE,
                           MAX(NVL(ENTRYDATEANDTIME, VOUCHERDATE)) AS LAST_USED
                    FROM CASHBANKENTRY
                    WHERE USERCODE = :usercode
                      AND PURPOSE IS NOT NULL
                      AND TRIM(PURPOSE) IS NOT NULL
                    GROUP BY PURPOSE
                    ORDER BY MAX(NVL(ENTRYDATEANDTIME, VOUCHERDATE)) DESC
                )
                WHERE ROWNUM <= 10
                """,
                {"usercode": int(usercode)},
            )

            purposes = [
                str(row[0] or "").strip()
                for row in cursor.fetchall()
                if str(row[0] or "").strip()
            ]

        return jsonify({"success": True, "purposes": purposes})

    except Exception as e:
        return jsonify({"success": False, "message": str(e), "purposes": []}), 500

    finally:
        if connection:
            connection.close()


@app.route("/api/cash-voucher-entry/defaults", methods=["GET"])
def cash_voucher_entry_defaults():
    if not session.get("logged_in"):
        return jsonify({
            "success": False,
            "message": "Login required",
            "username": "",
            "purposes": []
        }), 401

    connection = None
    try:
        username = str(session.get("username") or "").strip()
        usercode = session.get("usercode")
        purposes = []

        if usercode:
            connection = get_connection()
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT PURPOSE
                    FROM (
                        SELECT PURPOSE,
                               MAX(NVL(ENTRYDATEANDTIME, VOUCHERDATE)) AS LAST_USED
                        FROM CASHBANKENTRY
                        WHERE USERCODE = :usercode
                          AND PURPOSE IS NOT NULL
                          AND TRIM(PURPOSE) IS NOT NULL
                        GROUP BY PURPOSE
                        ORDER BY MAX(NVL(ENTRYDATEANDTIME, VOUCHERDATE)) DESC
                    )
                    WHERE ROWNUM <= 10
                    """,
                    {"usercode": int(usercode)}
                )

                purposes = [
                    str(row[0] or "").strip()
                    for row in cursor.fetchall()
                    if str(row[0] or "").strip()
                ]

        return jsonify({
            "success": True,
            "username": username,
            "purposes": purposes
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
            "username": str(session.get("username") or "").strip(),
            "purposes": []
        }), 500

    finally:
        if connection:
            connection.close()

if __name__ == "__main__":
    Timer(1, open_browser).start()
    app.run(host="0.0.0.0", port=5050, debug=False, use_reloader=False)
