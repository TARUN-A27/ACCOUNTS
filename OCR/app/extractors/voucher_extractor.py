import re


def extract_cash_payment_voucher(ocr_text):
    """
    Extracts fields from Cash Payment Voucher OCR text.
    Rule-based first version.
    """

    result = {
        "voucher_no": None,
        "date": None,
        "account_head": None,
        "person_name": None,
        "purpose": None,
        "amount_words": None,
        "amount": None,
        "confidence": "needs_review"
    }

    if not ocr_text:
        return result

    text = ocr_text

    date_match = re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", text)
    if date_match:
        result["date"] = date_match.group()

    amount_match = re.search(r"Rs\.?\s*[:\-]?\s*(\d+)", text, re.IGNORECASE)
    if amount_match:
        result["amount"] = amount_match.group(1)

    amount_words_match = re.search(
        r"amount in words\s*:?\s*(.*?)(cost centre|code no|amount|$)",
        text,
        re.IGNORECASE | re.DOTALL
    )
    if amount_words_match:
        result["amount_words"] = clean_text(amount_words_match.group(1))

    person_match = re.search(
        r"name of the person\s*:?\s*(.*?)(purpose|amount in words|$)",
        text,
        re.IGNORECASE | re.DOTALL
    )
    if person_match:
        result["person_name"] = clean_text(person_match.group(1))

    purpose_match = re.search(
        r"purpose\s*:?\s*(.*?)(amount in words|cost centre|code no|amount|$)",
        text,
        re.IGNORECASE | re.DOTALL
    )
    if purpose_match:
        result["purpose"] = clean_text(purpose_match.group(1))

    voucher_match = re.search(
        r"voucher\s*no\s*[:\-]?\s*([A-Za-z0-9/-]+)",
        text,
        re.IGNORECASE
    )
    if voucher_match:
        result["voucher_no"] = voucher_match.group(1)

    account_match = re.search(
        r"account head\s*:?\s*(.*?)(name of the person|purpose|$)",
        text,
        re.IGNORECASE | re.DOTALL
    )
    if account_match:
        result["account_head"] = clean_text(account_match.group(1))

    return result


def clean_text(value):
    value = value.replace("\n", " ")
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" :-")
    return value