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
            WHERE divisioncode IN (1,2,3,17,18,41)
            ORDER BY divisioncode
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
            SELECT usercode,
                   username,
                   password
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
                "usercode": str(row[0]),
                "username": str(row[1]),
                "valid": True
            }

        return {
            "usercode": None,
            "username": None,
            "valid": False
        }

    except Exception as e:
        print("Login Validation Error:", str(e))

        return {
            "usercode": None,
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


def increment_cpa_maxnumber(divisioncode, yearcode):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        print(f"CPA Update -> Division: {divisioncode}, YearCode: {yearcode}")

        cursor.execute("""
            SELECT maxnumber
            FROM NOCONFIG
            WHERE divisioncode = :divisioncode
              AND voctype = 'CPA'
              AND yearcode = :yearcode
            FOR UPDATE
        """, {
            "divisioncode": divisioncode,
            "yearcode": yearcode
        })

        row = cursor.fetchone()

        if not row:
            conn.rollback()
            return {
                "success": False,
                "message": f"No NOCONFIG record found for division {divisioncode}, VOCTYPE CPA, YEARCODE {yearcode}",
                "maxnumber": None
            }

        current_maxnumber = int(row[0])
        new_maxnumber = current_maxnumber + 1

        cursor.execute("""
            UPDATE NOCONFIG
            SET maxnumber = :new_maxnumber
            WHERE divisioncode = :divisioncode
              AND voctype = 'CPA'
              AND yearcode = :yearcode
        """, {
            "new_maxnumber": new_maxnumber,
            "divisioncode": divisioncode,
            "yearcode": yearcode
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


def get_year_codes():
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT YearCode,
                   YearName,
                   StartDate,
                   EndDate
            FROM inventory.InvPeriod
            ORDER BY 1
        """)

        years = []

        for row in cursor.fetchall():
            years.append({
                "yearcode": str(row[0]),
                "yearname": str(row[1]),
                "startdate": row[2],
                "enddate": row[3]
            })

        return years

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return years