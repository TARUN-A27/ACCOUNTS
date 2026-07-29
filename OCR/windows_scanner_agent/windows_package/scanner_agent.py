from flask import Flask, jsonify, send_file, make_response, request
from pathlib import Path
from datetime import datetime
import subprocess
import os

app = Flask(__name__)

SCAN_DIR = Path(r"C:\AIAccountsScanner\scans")
SCAN_DIR.mkdir(parents=True, exist_ok=True)

PROFILE_NAME = "AI_ACCOUNTS_ADF_A5"


def find_naps2_console():
    candidates = [
        r"C:\Program Files\NAPS2\NAPS2.Console.exe",
        r"C:\Program Files (x86)\NAPS2\NAPS2.Console.exe",
        r"C:\Users\%USERNAME%\AppData\Local\Programs\NAPS2\NAPS2.Console.exe",
    ]

    expanded = [os.path.expandvars(path) for path in candidates]

    for path in expanded:
        if Path(path).exists():
            return path

    # Last fallback: search common folders only
    search_roots = [
        Path(r"C:\Program Files"),
        Path(r"C:\Program Files (x86)"),
        Path(os.path.expandvars(r"C:\Users\%USERNAME%\AppData\Local\Programs")),
    ]

    for root in search_roots:
        if root.exists():
            found = list(root.rglob("NAPS2.Console.exe"))
            if found:
                return str(found[0])

    return None


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def options_response():
    return make_response("", 204)


@app.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return options_response()

    naps2_console = find_naps2_console()

    return jsonify({
        "success": True,
        "message": "AI-Accounts Windows Scanner Agent running",
        "profile": PROFILE_NAME,
        "naps2_found": bool(naps2_console),
        "naps2_console": naps2_console,
    })


@app.route("/scan", methods=["GET", "POST", "OPTIONS"])
def scan():
    if request.method == "OPTIONS":
        return options_response()

    try:
        naps2_console = find_naps2_console()

        if not naps2_console:
            return jsonify({
                "success": False,
                "message": "NAPS2.Console.exe not found. Install NAPS2 first.",
            }), 500

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = SCAN_DIR / f"scan_{timestamp}.pdf"

        command = [
            naps2_console,
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
                "message": "NAPS2 scan failed. Check scanner, ADF paper, and NAPS2 profile.",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": command,
            }), 500

        if not output_path.exists() or output_path.stat().st_size == 0:
            return jsonify({
                "success": False,
                "message": "Scan completed but PDF was not created.",
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=6060, debug=False)
