from validators.voucher_validator import validate_cash_payment_voucher


def validate_document(structured_output):
    classification = structured_output.get("classification", {})
    document_type = classification.get("document_type")
    fields = structured_output.get("fields", {})

    if document_type == "cash_payment_voucher":
        return validate_cash_payment_voucher(fields)

    return {
        "status": "needs_review",
        "requires_review": True,
        "missing_fields": [],
        "warnings": ["No validation rules found for this document type"],
        "errors": [],
    }