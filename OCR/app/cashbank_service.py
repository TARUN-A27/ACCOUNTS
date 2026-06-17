from datetime import datetime
import re

from database import get_connection


def clean_amount(value):
    if value is None:
        return 0

    text = str(value).replace(",", "")
    match = re.search(r"\d+(\.\d+)?", text)

    if not match:
        return 0

    return float(match.group())


def today_number():
    return int(datetime.now().strftime("%Y%m%d"))


def current_creation_datetime():
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def normalize_account_name(value):
    if not value:
        return ""

    text = str(value).upper()
    text = text.replace("\n", " ")
    text = text.replace("&", "AND")
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def find_account_code(search_text):
    if not search_text:
        return None

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cleaned_text = normalize_account_name(search_text)

        print("OCR Account Head :", repr(search_text))
        print("Normalized Search:", cleaned_text)

        cursor.execute("""
            SELECT ACCODE, NAME
            FROM ACCOUNTS
            WHERE UPPER(NAME) = :exact_name
              AND ROWNUM = 1
        """, {
            "exact_name": str(search_text).strip().upper()
        })

        row = cursor.fetchone()

        if row:
            print("Exact Account Match:", row)
            return str(row[0])

        cursor.execute("""
            SELECT ACCODE, NAME
            FROM ACCOUNTS
            WHERE UPPER(NAME) LIKE '%' || :search_text || '%'
              AND ROWNUM = 1
        """, {
            "search_text": str(search_text).strip().upper()
        })

        row = cursor.fetchone()

        if row:
            print("LIKE Account Match:", row)
            return str(row[0])

        cursor.execute("""
            SELECT ACCODE, NAME
            FROM ACCOUNTS
            WHERE REPLACE(
                    REPLACE(
                        REPLACE(
                            REGEXP_REPLACE(UPPER(NAME), '[^A-Z0-9 ]+', ' '),
                        '&', 'AND'),
                    '(', ' '),
                ')', ' ') LIKE '%' || :cleaned_text || '%'
              AND ROWNUM = 1
        """, {
            "cleaned_text": cleaned_text
        })

        row = cursor.fetchone()

        if row:
            print("Normalized Account Match:", row)
            return str(row[0])

        first_word = cleaned_text.split(" ")[0] if cleaned_text else ""

        if first_word:
            cursor.execute("""
                SELECT ACCODE, NAME
                FROM ACCOUNTS
                WHERE UPPER(NAME) LIKE '%' || :first_word || '%'
                  AND ROWNUM <= 10
            """, {
                "first_word": first_word
            })

            possible_rows = cursor.fetchall()

            print("Possible Account Matches:")
            for item in possible_rows:
                print(item)

        return None

    except Exception as e:
        print("Account Lookup Error:", str(e))
        return None

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def insert_taruncashbank(voucher_fields, session_data):
    conn = None
    cursor = None

    try:
        print("\n" + "=" * 80)
        print("Voucher Fields Received")
        print(voucher_fields)
        print("=" * 80)

        vocno = int(session_data.get("cpa_number"))
        divisioncode = int(session_data.get("divisioncode"))
        yearcode = int(session_data.get("yearcode"))
        usercode = int(session_data.get("usercode"))

        account_head = str(voucher_fields.get("account_head", "")).strip()
        narr = str(voucher_fields.get("purpose", "")).strip()
        amount = clean_amount(voucher_fields.get("amount"))

        print("\n" + "=" * 80)
        print("TARUNCASHBANK INSERT START")
        print("=" * 80)

        print("Account Head :", account_head)
        print("Narration    :", narr)
        print("Amount       :", amount)

        accode = find_account_code(account_head)
        ctcode = find_account_code("CASH ON HAND")

        print("ACCODE :", accode)
        print("CTCODE :", ctcode)

        if not accode:
            return {
                "success": False,
                "message": f"ACCODE not found in ACCOUNTS for account head: {account_head}"
            }

        if not ctcode:
            return {
                "success": False,
                "message": "CTCODE not found in ACCOUNTS for CASH ON HAND"
            }

        conn = get_connection()
        cursor = conn.cursor()

        insert_sql = """
            INSERT INTO TARUNCASHBANK (
                VOCNO,
                VOCDATE,
                VOCTYPE,
                ACCODE,
                CTCODE,
                COSTCODE,
                COSTGROUPCODE,
                NARR,
                AMOUNT,
                DEBIT,
                CREDIT,
                DIVISIONCODE,
                CLASS,
                PROJECT,
                YEARCODE,
                USERCODE,
                CREATIONDATETIME,
                CANCELSTATUS,
                CONTRASTATUS,
                REVERSECHARGE_STATUS,
                DISCPER,
                DISC,
                NONGSTPERIODEXPENSES,
                REGISTEREDPARTYSTATUS,
                CLAIMSTATUS,
                IMPORTTYPE,
                ENTRYFRAMESTATUS
            )
            VALUES (
                :vocno,
                :vocdate,
                'CPA',
                :accode,
                :ctcode,
                0,
                0,
                :narr,
                :amount,
                :amount,
                0,
                :divisioncode,
                0,
                0,
                :yearcode,
                :usercode,
                :creationdatetime,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0
            )
        """

        params = {
            "vocno": vocno,
            "vocdate": today_number(),
            "accode": accode,
            "ctcode": ctcode,
            "narr": narr,
            "amount": amount,
            "divisioncode": divisioncode,
            "yearcode": yearcode,
            "usercode": usercode,
            "creationdatetime": current_creation_datetime()
        }

        print("\nInsert Parameters")
        print(params)

        cursor.execute(insert_sql, params)
        conn.commit()

        print("\nTARUNCASHBANK INSERT SUCCESS")
        print("=" * 80)

        return {
            "success": True,
            "message": "Voucher inserted successfully",
            "vocno": vocno,
            "accode": accode,
            "ctcode": ctcode,
            "amount": amount
        }

    except Exception as e:
        if conn:
            conn.rollback()

        print("\nTARUNCASHBANK INSERT ERROR")
        print(str(e))

        return {
            "success": False,
            "message": str(e)
        }

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()