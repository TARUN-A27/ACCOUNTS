"""History API: the IA sees every log entry, anyone else only their own. No database needed.

    OCR/venv/bin/python -m unittest OCR/tests/test_history_scope.py
"""
import io
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

# main.py connects to Oracle on import; give it a stand-in.
database = types.ModuleType("database")
database.get_connection = lambda: None
sys.modules.setdefault("database", database)

import main  # noqa: E402


def client_for(usercode, **session_data):
    client = main.app.test_client()

    with client.session_transaction() as session:
        session.update(logged_in=True, usercode=usercode, **session_data)

    return client


class HistoryScopeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = tmp.name

        logs = os.path.join(self.base, "logs")
        dirs = {
            "BASE_DIR": self.base,
            "UPLOAD_DIR": os.path.join(self.base, "uploads"),
            "LOG_DIR": logs,
            "RAW_JSON_DIR": os.path.join(logs, "raw_json"),
            "CLEAN_JSON_DIR": os.path.join(logs, "clean_json"),
            "TEXT_DIR": os.path.join(logs, "text"),
            "ERROR_DIR": os.path.join(logs, "errors"),
        }

        for path in dirs.values():
            os.makedirs(path, exist_ok=True)

        for patcher in (
            mock.patch.multiple(main, **dirs),
            mock.patch.object(main, "is_ia_auth_user", lambda code: str(code) == "2008"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_log(self, kind, name, **data):
        folder = os.path.join(self.base, "logs", kind)
        os.makedirs(folder, exist_ok=True)

        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def history_of(self, usercode):
        return sorted(item["source_file"] for item in client_for(usercode).get("/api/history").get_json())

    def test_user_sees_only_their_own_and_ia_sees_all(self):
        self.write_log("structured", "a_structured.json", source_file="mine.png", usercode="1001")
        self.write_log("structured", "b_structured.json", source_file="theirs.png", usercode="1002")
        self.write_log("structured", "c_structured.json", source_file="unowned.png")
        self.write_log("review", "d_review.json", source_file="mine_reviewed.png", status="rejected", usercode="1001")
        self.write_log("review", "e_review.json", source_file="theirs_reviewed.png", status="rejected", usercode="1002")

        self.assertEqual(self.history_of("1001"), ["mine.png", "mine_reviewed.png"])
        self.assertEqual(
            self.history_of("2008"),
            ["mine.png", "mine_reviewed.png", "theirs.png", "theirs_reviewed.png", "unowned.png"],
        )

    def test_not_logged_in_gets_nothing(self):
        self.assertEqual(main.app.test_client().get("/api/history").status_code, 401)

    def test_new_logs_are_stamped_with_the_logged_in_user(self):
        ocr = {"status": "succeeded", "analyzeResult": {"readResults": [
            {"page": 1, "lines": [{"text": "CASH PAYMENT VOUCHER"}]}]}}

        with mock.patch.object(main, "call_computer_vision_ocr", return_value=ocr):
            uploaded = client_for("1001").post(
                "/upload", data={"document": (io.BytesIO(b"png"), "scan.png")}
            ).get_json()

        # The client claiming to be 1001 must not matter.
        client_for("1002").post("/review", json={"source_file": "reviewed.png", "status": "rejected", "usercode": "1001"})

        self.assertEqual(self.history_of("1001"), [uploaded["source_file"]])
        self.assertEqual(self.history_of("1002"), ["reviewed.png"])

    def test_cashbank_lookup_only_reads_the_viewers_rows(self):
        conn = mock.MagicMock()
        conn.cursor.return_value.fetchall.return_value = []

        for usercode, expected in (("1001", 1001), ("2008", None)):
            with mock.patch.object(main, "get_connection", return_value=conn):
                client_for(usercode, divisioncode="1", yearcode="26").get("/api/history")

            self.assertEqual(conn.cursor.return_value.execute.call_args.args[1]["usercode"], expected)


if __name__ == "__main__":
    unittest.main()
