from classifiers.document_classifier import classify_document
from extractors.voucher_extractor import extract_cash_payment_voucher


def build_structured_output(ocr_text):
    classification = classify_document(ocr_text)

    document_type = classification.get("document_type")

    structured_data = {
        "classification": classification,
        "fields": {},
        "requires_review": True
    }

    if document_type == "cash_payment_voucher":
        structured_data["fields"] = extract_cash_payment_voucher(ocr_text)
        structured_data["requires_review"] = True
        return structured_data

    structured_data["fields"] = {
        "raw_text": ocr_text
    }

    structured_data["requires_review"] = True
    return structured_data