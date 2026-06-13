import os
import json
from datetime import datetime
from werkzeug.utils import secure_filename


def save_review_log(base_dir, review_data):
    review_dir = os.path.join(base_dir, "logs", "review")
    os.makedirs(review_dir, exist_ok=True)

    source_file = review_data.get("source_file", "unknown_document")
    safe_name = secure_filename(source_file).rsplit(".", 1)[0]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_file_name = f"{timestamp}_{safe_name}_review.json"
    review_file_path = os.path.join(review_dir, review_file_name)

    review_record = {
        "source_file": source_file,
        "document_type": review_data.get("document_type"),
        "status": review_data.get("status"),
        "corrected_fields": review_data.get("corrected_fields", {}),
        "reviewed_by": review_data.get("reviewed_by", "admin"),
        "reviewed_at": datetime.now().isoformat()
    }

    with open(review_file_path, "w", encoding="utf-8") as f:
        json.dump(review_record, f, indent=4, ensure_ascii=False)

    return {
        "review_file": review_file_name,
        "review_path": review_file_path
    }