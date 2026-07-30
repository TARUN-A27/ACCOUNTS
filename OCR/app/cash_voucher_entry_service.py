from datetime import datetime
import re

from database import get_connection


def clean_amount(value):
    if value is None:
        return 0

    text = str(value).replace(",", "").strip()
    match = re.search(r"\d+(\.\d+)?", text)

    if not match:
        return 0

    return float(match.group())


def parse_voucher_date(value):
    if not value:
        return datetime.now()

    value = str(value).strip()

    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    return datetime.now()


def is_valid_petty_cash_account(account_name, account_head_code):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM accounts
            WHERE TRIM(UPPER(name)) = TRIM(UPPER(:account_name))
              AND TRIM(UPPER(accode)) = TRIM(UPPER(:account_head_code))
              AND (
                    pettycashflag = 1
                    OR (
                        pettycashflag = 0
                        AND REGEXP_LIKE(UPPER(name), '(^|[^A-Z])ADVANCE([^A-Z]|$)')
                    )
                  )
        """, {
            "account_name": account_name,
            "account_head_code": account_head_code
        })

        count = cursor.fetchone()[0]
        return count > 0

    except Exception:
        return False

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


def insert_cash_voucher_entry(data, session_data, entry_source="MANUAL"):
    conn = None
    cursor = None

    try:
        voucherdate = data.get("voucherdate")
        account_head_code = (data.get("account_head_code") or "").strip()
        account_name = (data.get("account_name") or "").strip().upper()
        person_name = (data.get("person_name") or "").strip()
        purpose = (data.get("purpose") or "").strip()
        amount = data.get("amount")

        invoice_no = (data.get("invoice_no") or "").strip()
        invoice_date = (data.get("invoice_date") or "").strip()
        party_code = (data.get("party_code") or "").strip()
        party_name = (data.get("party_name") or "").strip().upper()

        detail_rows = data.get("details") or []

        usercode = session_data.get("usercode")
        divcode = session_data.get("divisioncode")
        yearcode = session_data.get("yearcode")

        entry_source = (entry_source or "MANUAL").strip().upper()

        if not voucherdate:
            return {"success": False, "message": "Voucher date is required"}

        if not account_name or not account_head_code:
            return {"success": False, "message": "Please select a valid account head from the list"}

        if not person_name:
            return {"success": False, "message": "Person name is required"}

        if not purpose:
            return {"success": False, "message": "Purpose is required"}

        if amount in (None, ""):
            return {"success": False, "message": "Amount is required"}

        if not is_valid_petty_cash_account(account_name, account_head_code):
            return {"success": False, "message": "Please select a valid account head from the list"}

        conn = get_connection()
        cursor = conn.cursor()

        new_id_var = cursor.var(int)

        cursor.execute("""
            INSERT INTO CASHBANKENTRY (
                VOUCHERDATE,
                ACCOUNT_HEAD_CODE,
                ACCOUNT_NAME,
                PERSON_NAME,
                PURPOSE,
                AMOUNT,
                ENTRYDATEANDTIME,
                USERCODE,
                DIVCODE,
                YEARCODE,
                ENTRY_SOURCE,
                INVOICE_NO,
                INVOICE_DATE,
                PARTY_CODE,
                PARTY_NAME
            ) VALUES (
                TO_DATE(:voucherdate, 'YYYY-MM-DD'),
                :account_head_code,
                :account_name,
                :person_name,
                :purpose,
                :amount,
                SYSDATE,
                :usercode,
                :divcode,
                :yearcode,
                :entry_source,
                :invoice_no,
                CASE
                    WHEN :invoice_date IS NULL THEN NULL
                    ELSE TO_DATE(:invoice_date, 'YYYY-MM-DD')
                END,
                :party_code,
                :party_name
            )
            RETURNING ID INTO :new_id
        """, {
            "voucherdate": voucherdate,
            "account_head_code": account_head_code,
            "account_name": account_name,
            "person_name": person_name,
            "purpose": purpose,
            "amount": amount,
            "usercode": usercode,
            "divcode": divcode,
            "yearcode": yearcode,
            "entry_source": entry_source,
            "invoice_no": invoice_no or None,
            "invoice_date": invoice_date or None,
            "party_code": party_code or None,
            "party_name": party_name or None,
            "new_id": new_id_var
        })

        new_id = new_id_var.getvalue()
        if isinstance(new_id, list):
            new_id = new_id[0]

        saved_detail_count = 0

        for item in detail_rows:
            narration = (item.get("narration") or "").strip()
            item_count = item.get("count")
            sub_price = item.get("sub_price")
            total_price = item.get("total_price")

            if not narration and not item_count and not sub_price and not total_price:
                continue

            try:
                item_count_value = int(float(str(item_count).strip())) if str(item_count or "").strip() else None
            except Exception:
                item_count_value = None

            try:
                sub_price_value = float(str(sub_price).strip()) if str(sub_price or "").strip() else None
            except Exception:
                sub_price_value = None

            try:
                total_price_value = float(str(total_price).strip()) if str(total_price or "").strip() else None
            except Exception:
                total_price_value = None

            if total_price_value is None and item_count_value is not None and sub_price_value is not None:
                total_price_value = item_count_value * sub_price_value

            cursor.execute("""
                INSERT INTO CASHBANKENTRYDETAILS (
                    CASHBANKENTRY_ID,
                    NARRATION,
                    ITEM_COUNT,
                    SUB_PRICE,
                    TOTAL_PRICE,
                    ENTRYDATEANDTIME
                ) VALUES (
                    :cashbankentry_id,
                    :narration,
                    :item_count,
                    :sub_price,
                    :total_price,
                    SYSDATE
                )
            """, {
                "cashbankentry_id": new_id,
                "narration": narration or None,
                "item_count": item_count_value,
                "sub_price": sub_price_value,
                "total_price": total_price_value
            })

            saved_detail_count += 1

        conn.commit()

        return {
            "success": True,
            "message": "Cash voucher entry saved successfully",
            "id": new_id,
            "voucher_id": new_id,
            "details_saved": saved_detail_count
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {
            "success": False,
            "message": str(e)
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def list_cash_voucher_entries(limit=100):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM (
                SELECT
                    ID,
                    TO_CHAR(VOUCHERDATE, 'DD.MM.YYYY') AS VOUCHERDATE,
                    ACCOUNT_HEAD_CODE,
                    ACCOUNT_NAME,
                    PERSON_NAME,
                    PURPOSE,
                    AMOUNT,
                    TO_CHAR(ENTRYDATEANDTIME, 'DD.MM.YYYY HH24:MI:SS') AS ENTRYDATEANDTIME,
                    USERCODE,
                    DIVCODE,
                    YEARCODE,
                    AUTHUSERCODE,
                    TO_CHAR(AUTHDATEANDTIME, 'DD.MM.YYYY HH24:MI:SS') AS AUTHDATEANDTIME,
                    NVL(ENTRY_SOURCE, 'MANUAL') AS ENTRY_SOURCE
                FROM CASHBANKENTRY
                ORDER BY ID DESC
            )
            WHERE ROWNUM <= :limit
        """, {"limit": int(limit)})

        rows = []

        for row in cursor.fetchall():
            authusercode = row[11]

            rows.append({
                "id": row[0],
                "voucherdate": row[1],
                "account_head_code": row[2],
                "account_name": row[3],
                "person_name": row[4],
                "purpose": row[5],
                "amount": float(row[6] or 0),
                "entrydateandtime": row[7],
                "usercode": row[8],
                "divcode": row[9],
                "yearcode": row[10],
                "authusercode": authusercode,
                "authdateandtime": row[12],
                "authenticated": True if authusercode else False,
                "entry_source": row[13] if len(row) > 13 else "MANUAL"
            })

        return {
            "success": True,
            "rows": rows
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "rows": []
        }

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()



def get_cash_voucher_entry_by_id(voucher_id):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                ID,
                TO_CHAR(VOUCHERDATE, 'YYYY-MM-DD') AS VOUCHERDATE,
                ACCOUNT_HEAD_CODE,
                ACCOUNT_NAME,
                PERSON_NAME,
                PURPOSE,
                AMOUNT,
                TO_CHAR(ENTRYDATEANDTIME, 'DD.MM.YYYY HH24:MI:SS') AS ENTRYDATEANDTIME,
                USERCODE,
                DIVCODE,
                YEARCODE,
                AUTHUSERCODE,
                TO_CHAR(AUTHDATEANDTIME, 'DD.MM.YYYY HH24:MI:SS') AS AUTHDATEANDTIME,
                    NVL(ENTRY_SOURCE, 'MANUAL') AS ENTRY_SOURCE
            FROM CASHBANKENTRY
            WHERE ID = :id
        """, {"id": int(voucher_id)})

        row = cursor.fetchone()

        if not row:
            return {
                "success": False,
                "message": "Voucher not found"
            }

        authusercode = row[11]

        return {
            "success": True,
            "row": {
                "id": row[0],
                "voucherdate": row[1],
                "account_head_code": row[2],
                "account_name": row[3],
                "person_name": row[4],
                "purpose": row[5],
                "amount": float(row[6] or 0),
                "entrydateandtime": row[7],
                "usercode": row[8],
                "divcode": row[9],
                "yearcode": row[10],
                "authusercode": authusercode,
                "authdateandtime": row[12],
                "authenticated": True if authusercode else False,
                "entry_source": row[13] if len(row) > 13 else "MANUAL"
            }
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()



def update_cash_voucher_entry(voucher_id, data):
    conn = None
    cursor = None

    try:
        voucher_date = parse_voucher_date(data.get("voucherdate"))
        account_head_code = str(data.get("account_head_code") or "").strip()
        account_name = str(data.get("account_name") or "").strip()
        purpose = str(data.get("purpose") or "").strip()
        person_name = str(data.get("person_name") or "").strip()
        amount = clean_amount(data.get("amount"))

        if not voucher_date:
            return {"success": False, "message": "Date is required"}

        if not account_name:
            return {"success": False, "message": "Account head is required"}

        if not account_head_code:
            return {"success": False, "message": "Please select a valid account head from the list"}

        if not is_valid_petty_cash_account(account_name, account_head_code):
            return {"success": False, "message": "Invalid account head. Please select from the list only"}

        if not person_name:
            return {"success": False, "message": "Name of the person is required"}

        if not purpose:
            return {"success": False, "message": "Purpose is required"}

        if amount <= 0:
            return {"success": False, "message": "Amount must be greater than zero"}

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE CASHBANKENTRY
            SET
                VOUCHERDATE = :voucherdate,
                ACCOUNT_HEAD_CODE = :account_head_code,
                ACCOUNT_NAME = :account_name,
                PERSON_NAME = :person_name,
                PURPOSE = :purpose,
                AMOUNT = :amount,
                INVOICE_NO = :invoice_no,
                INVOICE_DATE = CASE WHEN :invoice_date IS NULL THEN NULL ELSE TO_DATE(:invoice_date, 'YYYY-MM-DD') END,
                PARTY_CODE = :party_code,
                PARTY_NAME = :party_name
            WHERE ID = :id
        """, {
            "voucherdate": voucher_date,
            "account_head_code": account_head_code,
            "account_name": account_name,
            "person_name": person_name,
            "purpose": purpose,
            "amount": amount,
            "id": int(voucher_id)
        })

        if cursor.rowcount == 0:
            conn.rollback()
            return {"success": False, "message": "Voucher not found"}

        conn.commit()

        return {
            "success": True,
            "message": "Voucher updated successfully",
            "id": int(voucher_id)
        }

    except Exception as e:
        if conn:
            conn.rollback()

        return {
            "success": False,
            "message": str(e)
        }

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


def list_petty_cash_accounts(account_type="others"):
    conn = None
    cursor = None

    try:
        account_type = (account_type or "others").strip().lower()

        conn = get_connection()
        cursor = conn.cursor()

        if account_type == "advance":
            cursor.execute("""
                SELECT name, accode
                FROM accounts
                WHERE pettycashflag = 0
                  AND REGEXP_LIKE(UPPER(name), '(^|[^A-Z])ADVANCE([^A-Z]|$)')
                ORDER BY name
            """)
        else:
            cursor.execute("""
                SELECT name, accode
                FROM accounts
                WHERE pettycashflag = 1
                ORDER BY name
            """)

        rows = []

        for row in cursor.fetchall():
            rows.append({
                "name": str(row[0] or ""),
                "accode": str(row[1] or ""),
                "type": account_type
            })

        return {
            "success": True,
            "rows": rows,
            "type": account_type
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "rows": [],
            "type": account_type
        }

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


def is_ia_auth_user(usercode):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT empcode,
                   username,
                   usercode,
                   PUNCHSTATUS,
                   INDENTPUNCHSTATUS,
                   MOBILE,
                   PASSWORD,
                   MRSSTATUS
            FROM rawuser
            WHERE usercode = :usercode
              AND usercode = 2008
        """, {
            "usercode": int(usercode)
        })

        row = cursor.fetchone()
        return row is not None

    except Exception:
        return False

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


def authenticate_cash_voucher_entry(voucher_id, auth_usercode):
    conn = None
    cursor = None

    try:
        if not auth_usercode:
            return {
                "success": False,
                "message": "Authentication user missing from session"
            }

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE CASHBANKENTRY
            SET
                AUTHUSERCODE = :authusercode,
                AUTHDATEANDTIME = SYSDATE
            WHERE ID = :id
        """, {
            "authusercode": int(auth_usercode),
            "id": int(voucher_id)
        })

        if cursor.rowcount == 0:
            conn.rollback()
            return {
                "success": False,
                "message": "Voucher not found"
            }

        conn.commit()

        return {
            "success": True,
            "message": "Voucher authenticated successfully",
            "id": int(voucher_id),
            "authusercode": int(auth_usercode)
        }

    except Exception as e:
        if conn:
            conn.rollback()

        return {
            "success": False,
            "message": str(e)
        }

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


# ============================================================
# DETAILS FEATURE OVERRIDES
# Supports CASHBANKENTRYDETAILS for:
# - edit load
# - update
# - voucher draft/list narration display
# ============================================================

def get_cash_voucher_details(voucher_id, cursor=None):
    own_conn = None
    own_cursor = None

    try:
        if cursor is None:
            own_conn = get_connection()
            own_cursor = own_conn.cursor()
            cursor = own_cursor

        cursor.execute("""
            SELECT ID,
                   CASHBANKENTRY_ID,
                   NARRATION,
                   ITEM_COUNT,
                   SUB_PRICE,
                   TOTAL_PRICE
            FROM CASHBANKENTRYDETAILS
            WHERE CASHBANKENTRY_ID = :voucher_id
            ORDER BY ID
        """, {
            "voucher_id": voucher_id
        })

        details = []
        for row in cursor.fetchall():
            details.append({
                "id": row[0],
                "cashbankentry_id": row[1],
                "narration": row[2] or "",
                "count": row[3] if row[3] is not None else "",
                "sub_price": float(row[4]) if row[4] is not None else "",
                "total_price": float(row[5]) if row[5] is not None else ""
            })

        return details

    except Exception:
        return []

    finally:
        if own_cursor:
            own_cursor.close()
        if own_conn:
            own_conn.close()


def save_cash_voucher_details(cursor, voucher_id, detail_rows):
    cursor.execute("""
        DELETE FROM CASHBANKENTRYDETAILS
        WHERE CASHBANKENTRY_ID = :voucher_id
    """, {
        "voucher_id": voucher_id
    })

    saved_count = 0

    for item in detail_rows or []:
        narration = (item.get("narration") or "").strip()
        item_count = item.get("count")
        sub_price = item.get("sub_price")
        total_price = item.get("total_price")

        if not narration and not item_count and not sub_price and not total_price:
            continue

        try:
            item_count_value = int(float(str(item_count).strip())) if str(item_count or "").strip() else None
        except Exception:
            item_count_value = None

        try:
            sub_price_value = float(str(sub_price).strip()) if str(sub_price or "").strip() else None
        except Exception:
            sub_price_value = None

        try:
            total_price_value = float(str(total_price).strip()) if str(total_price or "").strip() else None
        except Exception:
            total_price_value = None

        if total_price_value is None and item_count_value is not None and sub_price_value is not None:
            total_price_value = item_count_value * sub_price_value

        cursor.execute("""
            INSERT INTO CASHBANKENTRYDETAILS (
                CASHBANKENTRY_ID,
                NARRATION,
                ITEM_COUNT,
                SUB_PRICE,
                TOTAL_PRICE,
                ENTRYDATEANDTIME
            ) VALUES (
                :cashbankentry_id,
                :narration,
                :item_count,
                :sub_price,
                :total_price,
                SYSDATE
            )
        """, {
            "cashbankentry_id": voucher_id,
            "narration": narration or None,
            "item_count": item_count_value,
            "sub_price": sub_price_value,
            "total_price": total_price_value
        })

        saved_count += 1

    return saved_count


def list_cash_voucher_entries(limit=100):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM (
                SELECT h.ID,
                       TO_CHAR(h.VOUCHERDATE, 'YYYY-MM-DD') AS VOUCHERDATE,
                       h.ACCOUNT_HEAD_CODE,
                       h.ACCOUNT_NAME,
                       h.PERSON_NAME,
                       h.PURPOSE,
                       h.AMOUNT,
                       TO_CHAR(h.ENTRYDATEANDTIME, 'YYYY-MM-DD HH24:MI:SS') AS ENTRYDATEANDTIME,
                       h.USERCODE,
                       h.DIVCODE,
                       h.YEARCODE,
                       h.AUTHUSERCODE,
                       TO_CHAR(h.AUTHDATEANDTIME, 'YYYY-MM-DD HH24:MI:SS') AS AUTHDATEANDTIME,
                       NVL(h.ENTRY_SOURCE, 'MANUAL') AS ENTRY_SOURCE,
                       h.INVOICE_NO,
                       TO_CHAR(h.INVOICE_DATE, 'YYYY-MM-DD') AS INVOICE_DATE,
                       h.PARTY_CODE,
                       h.PARTY_NAME,
                       (
                           SELECT LISTAGG(d.NARRATION, CHR(10)) WITHIN GROUP (ORDER BY d.ID)
                           FROM CASHBANKENTRYDETAILS d
                           WHERE d.CASHBANKENTRY_ID = h.ID
                             AND d.NARRATION IS NOT NULL
                       ) AS NARRATION
                FROM CASHBANKENTRY h
                ORDER BY h.ID DESC
            )
            WHERE ROWNUM <= :limit
        """, {
            "limit": int(limit or 100)
        })

        entries = []

        for row in cursor.fetchall():
            entries.append({
                "id": row[0],
                "voucherdate": row[1],
                "account_head_code": row[2] or "",
                "account_name": row[3] or "",
                "person_name": row[4] or "",
                "purpose": row[5] or "",
                "amount": float(row[6]) if row[6] is not None else 0,
                "entrydateandtime": row[7] or "",
                "usercode": row[8],
                "divcode": row[9],
                "yearcode": row[10],
                "authusercode": row[11],
                "authdatetime": row[12] or "",
                "authenticated": row[11] is not None,
                "entry_source": row[13] or "MANUAL",
                "invoice_no": row[14] or "",
                "invoice_date": row[15] or "",
                "party_code": row[16] or "",
                "party_name": row[17] or "",
                "narration": row[18] or ""
            })

        return {
            "success": True,
            "entries": entries
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "entries": []
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def get_cash_voucher_entry_by_id(voucher_id):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ID,
                   TO_CHAR(VOUCHERDATE, 'YYYY-MM-DD') AS VOUCHERDATE,
                   ACCOUNT_HEAD_CODE,
                   ACCOUNT_NAME,
                   PERSON_NAME,
                   PURPOSE,
                   AMOUNT,
                   TO_CHAR(ENTRYDATEANDTIME, 'YYYY-MM-DD HH24:MI:SS') AS ENTRYDATEANDTIME,
                   USERCODE,
                   DIVCODE,
                   YEARCODE,
                   AUTHUSERCODE,
                   TO_CHAR(AUTHDATEANDTIME, 'YYYY-MM-DD HH24:MI:SS') AS AUTHDATEANDTIME,
                   NVL(ENTRY_SOURCE, 'MANUAL') AS ENTRY_SOURCE,
                   INVOICE_NO,
                   TO_CHAR(INVOICE_DATE, 'YYYY-MM-DD') AS INVOICE_DATE,
                   PARTY_CODE,
                   PARTY_NAME
            FROM CASHBANKENTRY
            WHERE ID = :voucher_id
        """, {
            "voucher_id": voucher_id
        })

        row = cursor.fetchone()

        if not row:
            return {
                "success": False,
                "message": "Voucher not found"
            }

        details = get_cash_voucher_details(voucher_id, cursor)

        narration_lines = []
        for d in details:
            if d.get("narration"):
                narration_lines.append(d.get("narration"))

        voucher = {
            "id": row[0],
            "voucherdate": row[1],
            "account_head_code": row[2] or "",
            "account_name": row[3] or "",
            "person_name": row[4] or "",
            "purpose": row[5] or "",
            "amount": float(row[6]) if row[6] is not None else 0,
            "entrydateandtime": row[7] or "",
            "usercode": row[8],
            "divcode": row[9],
            "yearcode": row[10],
            "authusercode": row[11],
            "authdatetime": row[12] or "",
            "authenticated": row[11] is not None,
            "entry_source": row[13] or "MANUAL",
            "invoice_no": row[14] or "",
            "invoice_date": row[15] or "",
            "party_code": row[16] or "",
            "party_name": row[17] or "",
            "details": details,
            "narration": "\n".join(narration_lines)
        }

        return {
            "success": True,
            "voucher": voucher,
            "entry": voucher
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def update_cash_voucher_entry(voucher_id, data):
    conn = None
    cursor = None

    try:
        voucherdate = data.get("voucherdate")
        account_head_code = (data.get("account_head_code") or "").strip()
        account_name = (data.get("account_name") or "").strip().upper()
        person_name = (data.get("person_name") or "").strip()
        purpose = (data.get("purpose") or "").strip()
        amount = data.get("amount")

        invoice_no = (data.get("invoice_no") or "").strip()
        invoice_date = (data.get("invoice_date") or "").strip()
        party_code = (data.get("party_code") or "").strip()
        party_name = (data.get("party_name") or "").strip().upper()
        detail_rows = data.get("details") or []

        if not voucherdate:
            return {"success": False, "message": "Voucher date is required"}

        if not account_name or not account_head_code:
            return {"success": False, "message": "Please select a valid account head from the list"}

        if not person_name:
            return {"success": False, "message": "Person name is required"}

        if not purpose:
            return {"success": False, "message": "Purpose is required"}

        if amount in (None, ""):
            return {"success": False, "message": "Amount is required"}

        if not is_valid_petty_cash_account(account_name, account_head_code):
            return {"success": False, "message": "Please select a valid account head from the list"}

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT AUTHUSERCODE
            FROM CASHBANKENTRY
            WHERE ID = :voucher_id
        """, {
            "voucher_id": voucher_id
        })

        auth_row = cursor.fetchone()

        if not auth_row:
            return {"success": False, "message": "Voucher not found"}

        if auth_row[0] is not None:
            return {"success": False, "message": "Authenticated voucher cannot be edited"}

        cursor.execute("""
            UPDATE CASHBANKENTRY
            SET VOUCHERDATE = TO_DATE(:voucherdate, 'YYYY-MM-DD'),
                ACCOUNT_HEAD_CODE = :account_head_code,
                ACCOUNT_NAME = :account_name,
                PERSON_NAME = :person_name,
                PURPOSE = :purpose,
                AMOUNT = :amount,
                INVOICE_NO = :invoice_no,
                INVOICE_DATE = CASE
                    WHEN :invoice_date IS NULL THEN NULL
                    ELSE TO_DATE(:invoice_date, 'YYYY-MM-DD')
                END,
                PARTY_CODE = :party_code,
                PARTY_NAME = :party_name
            WHERE ID = :voucher_id
        """, {
            "voucher_id": voucher_id,
            "voucherdate": voucherdate,
            "account_head_code": account_head_code,
            "account_name": account_name,
            "person_name": person_name,
            "purpose": purpose,
            "amount": amount,
            "invoice_no": invoice_no or None,
            "invoice_date": invoice_date or None,
            "party_code": party_code or None,
            "party_name": party_name or None
        })

        details_saved = save_cash_voucher_details(cursor, voucher_id, detail_rows)

        conn.commit()

        return {
            "success": True,
            "message": "Voucher updated successfully",
            "id": voucher_id,
            "details_saved": details_saved
        }

    except Exception as e:
        if conn:
            conn.rollback()
        return {
            "success": False,
            "message": str(e)
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

