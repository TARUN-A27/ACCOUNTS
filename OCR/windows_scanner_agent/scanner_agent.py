from flask import Flask, jsonify, send_file, make_response
from pathlib import Path
from datetime import datetime
import subprocess

app = Flask(__name__)

SCAN_DIR = Path(r"C:\AIAccountsScanner\scans")
SCAN_DIR.mkdir(parents=True, exist_ok=True)

NAPS2_CONSOLE = r"C:\Program Files\NAPS2\NAPS2.Console.exe"
PROFILE_NAME = "AI_ACCOUNTS_ADF_A5"


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request_is_options():
        return options_response()

    return jsonify({
        "success": True,
        "message": "AI-Accounts Windows Scanner Agent running",
        "profile": PROFILE_NAME,
        "naps2_console": NAPS2_CONSOLE,
    })


@app.route("/scan", methods=["GET", "POST", "OPTIONS"])
def scan():
    if request_is_options():
        return options_response()

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = SCAN_DIR / f"scan_{timestamp}.pdf"

        command = [
            NAPS2_CONSOLE,
            "-p", PROFILE_NAME,
            "-o", str(output_path),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
        )

        if result.returncode != 0:
            return jsonify({
                "success": False,
                "message": "NAPS2 scan failed",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": command,
            }), 500

        if not output_path.exists() or output_path.stat().st_size == 0:
            return jsonify({
                "success": False,
                "message": "Scan completed but PDF was not created",
                "stdout": result.stdout,
                "stderr": result.stderr,
            }), 500

        return send_file(
            output_path,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=output_path.name,
        )

    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "message": "Scanner timeout. Check ADF paper and try again.",
        }), 500

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
        }), 500


def request_is_options():
    from flask import request
    return request.method == "OPTIONS"


def options_response():
    return make_response("", 204)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=6060, debug=False)
