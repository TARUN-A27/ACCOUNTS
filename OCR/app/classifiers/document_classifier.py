def classify_document(ocr_text):
    """
    Classifies document type using simple keyword rules.
    Later we can replace/improve this with ML or LLM classification.
    """

    if not ocr_text:
        return {
            "document_type": "unknown",
            "confidence": 0.0,
            "reason": "Empty OCR text"
        }

    text = ocr_text.lower()

    if "cash payment voucher" in text or "voucher" in text:
        return {
            "document_type": "cash_payment_voucher",
            "confidence": 0.95,
            "reason": "Voucher keyword found"
        }

    if "tax invoice" in text:
        return {
            "document_type": "tax_invoice",
            "confidence": 0.95,
            "reason": "Tax invoice keyword found"
        }

    if "invoice" in text:
        return {
            "document_type": "invoice",
            "confidence": 0.90,
            "reason": "Invoice keyword found"
        }

    if "receipt" in text:
        return {
            "document_type": "receipt",
            "confidence": 0.90,
            "reason": "Receipt keyword found"
        }

    if "delivery challan" in text or "challan" in text:
        return {
            "document_type": "delivery_challan",
            "confidence": 0.90,
            "reason": "Challan keyword found"
        }

    if "purchase order" in text or "po no" in text:
        return {
            "document_type": "purchase_order",
            "confidence": 0.85,
            "reason": "Purchase order keyword found"
        }

    return {
        "document_type": "unknown",
        "confidence": 0.30,
        "reason": "No matching keyword found"
    }