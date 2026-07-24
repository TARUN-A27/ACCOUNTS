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
            WHERE pettycashflag = 1
              AND TRIM(UPPER(name)) = TRIM(UPPER(:account_name))
              AND TRIM(UPPER(accode)) = TRIM(UPPER(:account_head_code))
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


def insert_cash_voucher_entry(data, session_data):
    conn = None
    cursor = None

    try:
        voucher_date = parse_voucher_date(data.get("voucherdate"))
        account_head_code = str(data.get("account_head_code") or "").strip()
        account_name = str(data.get("account_name") or "").strip()
        purpose = str(data.get("purpose") or "").strip()
        person_name = str(data.get("person_name") or "").strip()
        amount = clean_amount(data.get("amount"))

        usercode = session_data.get("usercode")
        divcode = session_data.get("divisioncode")
        yearcode = session_data.get("yearcode")

        if not usercode:
            return {"success": False, "message": "User code missing from session"}

        if not divcode:
            return {"success": False, "message": "Division code missing from session"}

        if not yearcode:
            return {"success": False, "message": "Year code missing from session"}

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

        out_id = cursor.var(int)

        cursor.execute("""
            INSERT INTO CASHBANKENTRY (
                VOUCHERDATE,
                ACCOUNT_HEAD_CODE,
                ACCOUNT_NAME,
                PERSON_NAME,
                PURPOSE,
                AMOUNT,
                USERCODE,
                DIVCODE,
                YEARCODE
            )
            VALUES (
                :voucherdate,
                :account_head_code,
                :account_name,
                :person_name,
                :purpose,
                :amount,
                :usercode,
                :divcode,
                :yearcode
            )
            RETURNING ID INTO :out_id
        """, {
            "voucherdate": voucher_date,
            "account_head_code": account_head_code,
            "account_name": account_name,
            "person_name": person_name,
            "purpose": purpose,
            "amount": amount,
            "usercode": int(usercode),
            "divcode": int(divcode),
            "yearcode": int(yearcode),
            "out_id": out_id
        })

        conn.commit()

        voucher_id = out_id.getvalue()[0]

        return {
            "success": True,
            "message": "Cash voucher entry saved",
            "id": voucher_id,
            "voucherdate": voucher_date.strftime("%d.%m.%Y"),
            "account_head_code": account_head_code,
            "account_name": account_name,
            "person_name": person_name,
            "purpose": purpose,
            "amount": amount
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
                    TO_CHAR(AUTHDATEANDTIME, 'DD.MM.YYYY HH24:MI:SS') AS AUTHDATEANDTIME
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
                "authenticated": True if authusercode else False
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
                TO_CHAR(AUTHDATEANDTIME, 'DD.MM.YYYY HH24:MI:SS') AS AUTHDATEANDTIME
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
                "authenticated": True if authusercode else False
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
                AMOUNT = :amount
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


def list_petty_cash_accounts():
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

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
                "accode": str(row[1] or "")
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
