from flask import Flask, jsonify, send_file
from pathlib import Path
from datetime import datetime
import subprocess

app = Flask(__name__)

SCAN_DIR = Path(r"C:\AIAccountsScanner\scans")
SCAN_DIR.mkdir(parents=True, exist_ok=True)

# Change this path if NAPS2 is installed in another location
NAPS2_CONSOLE = r"C:\Program Files\NAPS2\NAPS2.Console.exe"

# Create this profile inside NAPS2 on Windows
PROFILE_NAME = "AI_ACCOUNTS_ADF_A5"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "success": True,
        "message": "AI-Accounts Windows Scanner Agent running",
        "profile": PROFILE_NAME,
        "naps2_console": NAPS2_CONSOLE,
    })


@app.route("/scan", methods=["GET", "POST"])
def scan():
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=6060, debug=False)
