"""Voucher list API: the IA sees every voucher, anyone else only their own. No database needed.

    OCR/venv/bin/python -m unittest OCR/tests/test_list_scope.py
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

# main.py connects to Oracle on import; give it a stand-in.
database = types.ModuleType("database")
database.get_connection = lambda: None
sys.modules.setdefault("database", database)

import main  # noqa: E402


class ListScopeTest(unittest.TestCase):
    def usercode_used_for(self, session_usercode):
        client = main.app.test_client()

        with client.session_transaction() as session:
            session.update(logged_in=True, usercode=session_usercode)

        with mock.patch.object(main, "is_ia_auth_user", lambda code: str(code) == "2008"), \
                mock.patch.object(main, "list_cash_voucher_entries", return_value={"success": True, "rows": []}) as listing:
            client.get("/api/cash-voucher-entry/list")

        return listing.call_args.kwargs["usercode"]

    def test_ia_sees_every_voucher(self):
        self.assertIsNone(self.usercode_used_for("2008"))

    def test_user_sees_only_their_own(self):
        self.assertEqual(self.usercode_used_for("1001"), 1001)

    def test_session_without_usercode_sees_nothing(self):
        self.assertEqual(self.usercode_used_for(None), 0)


if __name__ == "__main__":
    unittest.main()
