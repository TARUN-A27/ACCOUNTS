import base64
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)

PROFILE_NAME = os.environ.get("AI_ACCOUNTS_NAPS2_PROFILE", "AI_ACCOUNTS_ADF_A5")
AGENT_PORT = int(os.environ.get("AI_ACCOUNTS_AGENT_PORT", "6060"))


def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.after_request
def after_request(response):
    return add_cors(response)


def find_naps2_console():
    candidates = [
        r"C:\Program Files\NAPS2\NAPS2.Console.exe",
        r"C:\Program Files (x86)\NAPS2\NAPS2.Console.exe",
        str(Path.home() / "AppData" / "Local" / "Programs" / "NAPS2" / "NAPS2.Console.exe"),
        "NAPS2.Console.exe",
    ]

    for item in candidates:
        if item == "NAPS2.Console.exe":
            return item

        if Path(item).exists():
            return item

    return None


@app.route("/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return add_cors(jsonify({"success": True}))

    naps2 = find_naps2_console()

    return jsonify({
        "success": True,
        "message": "AI-Accounts Windows Scanner Agent running",
        "naps2_found": bool(naps2),
        "naps2_path": naps2 or "",
        "profile": PROFILE_NAME,
        "port": AGENT_PORT
    })


@app.route("/scan", methods=["GET", "POST", "OPTIONS"])
def scan():
    if request.method == "OPTIONS":
        return add_cors(jsonify({"success": True}))

    naps2 = find_naps2_console()

    if not naps2:
        return jsonify({
            "success": False,
            "message": "NAPS2.Console.exe not found. Install NAPS2 on this Windows PC."
        }), 500

    payload = request.get_json(silent=True) or {}
    output_format = str(payload.get("format") or request.args.get("format") or "pdf").lower()

    if output_format not in ("pdf", "png", "jpg", "jpeg", "tif", "tiff"):
        output_format = "pdf"

    ext = "jpg" if output_format == "jpeg" else output_format
    mime_type = {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "tif": "image/tiff",
        "tiff": "image/tiff",
    }.get(ext, "application/pdf")

    temp_dir = Path(tempfile.gettempdir()) / "ai_accounts_scans"
    temp_dir.mkdir(parents=True, exist_ok=True)

    output_path = temp_dir / f"ai_accounts_scan_{uuid.uuid4().hex}.{ext}"

    command_attempts = [
        [naps2, "scan", "--profile", PROFILE_NAME, "--output", str(output_path)],
        [naps2, "scan", "-p", PROFILE_NAME, "-o", str(output_path)],
        [naps2, "-p", PROFILE_NAME, "-o", str(output_path), "scan"],
        [naps2, "-o", str(output_path), "-p", PROFILE_NAME, "scan"],
    ]

    errors = []

    for command in command_attempts:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180
            )

            if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                data = output_path.read_bytes()

                return jsonify({
                    "success": True,
                    "message": "Scan completed",
                    "filename": output_path.name,
                    "mime_type": mime_type,
                    "size": len(data),
                    "file_base64": base64.b64encode(data).decode("ascii")
                })

            errors.append({
                "command": " ".join(command),
                "returncode": result.returncode,
                "stdout": result.stdout[-1000:],
                "stderr": result.stderr[-1000:]
            })

        except Exception as exc:
            errors.append({
                "command": " ".join(command),
                "error": str(exc)
            })

    return jsonify({
        "success": False,
        "message": "Scan failed. Check scanner, NAPS2 profile, and paper in ADF.",
        "profile": PROFILE_NAME,
        "errors": errors[-3:]
    }), 500


if __name__ == "__main__":
    print("AI-Accounts Windows Scanner Agent")
    print("Open only on this Windows PC: http://127.0.0.1:6060/health")
    print("NAPS2 profile required:", PROFILE_NAME)
    app.run(host="127.0.0.1", port=AGENT_PORT, debug=False)
