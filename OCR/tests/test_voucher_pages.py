"""static/voucher_pages.js: after packing, no voucher page is taller than an A4 sheet and no On Duty
row is lost. Uses the real Voucher Draft print CSS in headless Chrome; skipped when Chrome is missing.

    python3 -m unittest OCR/tests/test_voucher_pages.py
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = shutil.which("google-chrome") or shutil.which("chromium")

with open(os.path.join(HERE, "..", "templates", "voucher_draft.html"), encoding="utf-8") as f:
    PRINT_CSS = re.search(r"const css = `\s*(<style>.*?</style>)\s*`;", f.read(), re.S).group(1)

PAGE = """<!DOCTYPE html><html><head>%(css)s</head><body>
<div class="print-box">
  <div class="print-company">Amarjothi Spinning Mills Limited</div>
  <div class="print-title">CASH PAYMENT VOUCHER</div>
  <div class="print-line"><div class="print-label">ACCOUNT HEAD</div><div class="print-value">AJSM - MILL</div></div>
  <div class="print-line print-purpose"><div class="print-label">NARRATION</div><div class="print-value">TEA/FOOD EXPENSES</div></div>
  <div class="print-line preview-details-row"><div class="print-label">DETAILS</div><div class="print-value">
    <table class="preview-details-table"><thead><tr><th>Narration</th><th>Count</th></tr></thead>
    <tbody>%(details)s</tbody></table></div></div>
  <div class="print-line preview-on-duty-row"><div class="print-label">ON DUTY</div><div class="print-value">
    <table class="preview-details-table preview-on-duty-table"><thead><tr><th style="width:22%%;">Person Name</th>
    <th style="width:13%%;">Date</th><th style="width:12%%;">From Time</th><th style="width:12%%;">To Time</th>
    <th style="width:18%%;">Reason</th><th style="width:23%%;">Remark</th></tr></thead>
    <tbody>%(on_duty)s</tbody></table></div></div>
  <div class="print-amount-row"><div class="print-amount-words">AMOUNT IN WORDS : Rs. Two Thousand</div>
    <div class="print-amount-value">AMOUNT<br>Rs. 2859.00</div></div>
  <div class="print-signatures" style="height:92px;">%(signatures)s</div>
</div>
<script src="file://%(script)s"></script>
<script>
  packVoucherPages(document.body, "calc(190mm - 24px)");
  const pages = Array.from(document.querySelectorAll(".voucher-page"));
  const rows = document.querySelectorAll(".voucher-page .preview-on-duty-row tbody tr").length;
  const tallest = Math.max(...pages.map(p => p.getBoundingClientRect().height));
  document.title = "pages=" + pages.length + " rows=" + rows + " tallest=" + Math.round(tallest);
</script></body></html>"""

A4_PRINTABLE_PX = 277 / 25.4 * 96


def run_in_chrome(rows, remark, detail_rows=4):
    cells = "".join(
        '<div class="print-sign-cell" style="height:92px;display:flex;align-items:flex-end;">%s</div>' % name
        for name in ("DEPT. HEAD", "MD/JMD", "Accounts", "I.A.", "CASHIER", "RECEIVED BY")
    )
    html = PAGE % {
        "css": PRINT_CSS,
        "details": "<tr><td>TEA SNAKS/WATER/FOOD EXPENCES</td><td>1</td></tr>" * detail_rows,
        "on_duty": ("<tr><td>SIVAKUMAR_QC</td><td>12-10-2026</td><td>12:36</td><td>21:45</td>"
                    "<td>TIRUPUR</td><td>%s</td></tr>" % remark) * rows,
        "signatures": cells,
        "script": os.path.abspath(os.path.join(HERE, "..", "static", "voucher_pages.js")),
    }

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "voucher.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)

        dom = subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=718,1200",
             "--dump-dom", "file://" + path],
            capture_output=True, text=True, timeout=60,
        ).stdout

    found = re.search(r"<title>pages=(\d+) rows=(\d+) tallest=(\d+)</title>", dom)
    assert found, "packVoucherPages did not run:\n" + dom[-500:]
    return [int(n) for n in found.groups()]


@unittest.skipUnless(CHROME, "needs Google Chrome or Chromium")
class VoucherPagesTest(unittest.TestCase):
    def check(self, rows, remark, **kwargs):
        pages, kept, tallest = run_in_chrome(rows, remark, **kwargs)
        self.assertEqual(kept, rows, "On Duty rows were lost")
        self.assertLessEqual(tallest, A4_PRINTABLE_PX, "a voucher page is taller than an A4 sheet")
        return pages

    def test_one_row_is_one_page(self):
        self.assertEqual(self.check(1, "SHORT REMARK"), 1)

    def test_three_short_rows_share_a_page(self):
        self.assertEqual(self.check(3, "MY SELF VISIT HO AND TITUPUR OUR CUSTOMERS"), 1)

    def test_long_remarks_get_more_pages_instead_of_overflowing(self):
        remark = "MY SELF AND THE QC TEAM VISITED THE CUSTOMER MILL TO DISCUSS THE YARN COUNT VARIATION. " * 6
        self.assertGreater(self.check(6, remark, detail_rows=14), 2)   # more than 3 rows per page would give

    def test_at_most_three_rows_per_page(self):
        self.assertEqual(self.check(10, "OK"), 4)


if __name__ == "__main__":
    unittest.main()
