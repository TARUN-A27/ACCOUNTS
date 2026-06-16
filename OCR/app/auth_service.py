from database import get_connection


def get_all_divisions():
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT divisioncode, divdesc
            FROM DIVISION
            ORDER BY divdesc
        """)

        divisions = []

        for row in cursor.fetchall():
            divisions.append({
                "divisioncode": str(row[0]),
                "divdesc": str(row[1])
            })

        return divisions

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def validate_user(username, password):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT username, password
            FROM rawuser
            WHERE username = :username
              AND password = :password
        """, {
            "username": username,
            "password": password
        })

        row = cursor.fetchone()

        if row:
            return {
                "username": row[0],
                "valid": True
            }

        return {
            "username": None,
            "valid": False
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def create_user(username, password):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM rawuser
            WHERE username = :username
        """, {
            "username": username
        })

        count = cursor.fetchone()[0]

        if count > 0:
            return {
                "success": False,
                "message": "Username already exists"
            }

        cursor.execute("""
            INSERT INTO rawuser (username, password)
            VALUES (:username, :password)
        """, {
            "username": username,
            "password": password
        })

        conn.commit()

        return {
            "success": True,
            "message": "Account created successfully"
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


def get_division_details(divisioncode):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT divisioncode, divdesc
            FROM DIVISION
            WHERE divisioncode = :divisioncode
        """, {
            "divisioncode": divisioncode
        })

        row = cursor.fetchone()

        if not row:
            return None

        return {
            "divisioncode": str(row[0]),
            "divdesc": str(row[1])
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def increment_cpa_maxnumber(divisioncode):
    """
    Reads NOCONFIG using:
    divisioncode = selected divisioncode
    voctype = 'CPA'
    yearcode = 21

    Then updates:
    maxnumber = maxnumber + 1
    """

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT maxnumber
            FROM NOCONFIG
            WHERE divisioncode = :divisioncode
              AND voctype = 'CPA'
              AND yearcode = 21
            FOR UPDATE
        """, {
            "divisioncode": divisioncode
        })

        row = cursor.fetchone()

        if not row:
            conn.rollback()
            return {
                "success": False,
                "message": "No NOCONFIG record found for selected division, VOCTYPE CPA and YEARCODE 21",
                "maxnumber": None
            }

        current_maxnumber = int(row[0])
        new_maxnumber = current_maxnumber + 1

        cursor.execute("""
            UPDATE NOCONFIG
            SET maxnumber = :new_maxnumber
            WHERE divisioncode = :divisioncode
              AND voctype = 'CPA'
              AND yearcode = 21
        """, {
            "new_maxnumber": new_maxnumber,
            "divisioncode": divisioncode
        })

        conn.commit()

        return {
            "success": True,
            "message": "CPA number updated successfully",
            "old_maxnumber": current_maxnumber,
            "maxnumber": new_maxnumber
        }

    except Exception as e:
        if conn:
            conn.rollback()

        return {
            "success": False,
            "message": str(e),
            "maxnumber": None
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()