import re


REQUIRED_VOUCHER_FIELDS = [
    "date",
    "person_name",
    "purpose",
    "amount",
    "amount_words",
]


def validate_cash_payment_voucher(fields):
    validation = {
        "status": "valid",
        "requires_review": False,
        "missing_fields": [],
        "warnings": [],
        "errors": [],
    }

    for field in REQUIRED_VOUCHER_FIELDS:
        value = fields.get(field)

        if value is None or str(value).strip() == "":
            validation["missing_fields"].append(field)

    if validation["missing_fields"]:
        validation["status"] = "needs_review"
        validation["requires_review"] = True
        validation["warnings"].append("Some required fields are missing")

    amount = fields.get("amount")
    if amount and not str(amount).isdigit():
        validation["status"] = "needs_review"
        validation["requires_review"] = True
        validation["errors"].append("Amount is not numeric")

    date = fields.get("date")
    if date and not is_valid_date_format(date):
        validation["status"] = "needs_review"
        validation["requires_review"] = True
        validation["errors"].append("Date format is invalid")

    if fields.get("confidence") == "needs_review":
        validation["status"] = "needs_review"
        validation["requires_review"] = True
        validation["warnings"].append("OCR confidence requires manual review")

    return validation


def is_valid_date_format(value):
    return bool(re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$", str(value).strip()))