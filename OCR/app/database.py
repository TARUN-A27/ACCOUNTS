import os
import oracledb
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

DB_HOST = os.getenv("DB_HOST", "103.171.13.142")
DB_PORT = os.getenv("DB_PORT", "1530")
DB_SERVICE = os.getenv("DB_SERVICE", "arun")

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

ORACLE_CLIENT_LIB_DIR = os.getenv(
    "ORACLE_CLIENT_LIB_DIR",
    "/opt/oracle/instantclient_21_19"
)

oracledb.init_oracle_client(lib_dir=ORACLE_CLIENT_LIB_DIR)


def get_connection():
    dsn = f"{DB_HOST}:{DB_PORT}/{DB_SERVICE}"

    return oracledb.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        dsn=dsn
    )


def test_connection():
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT SYSDATE FROM dual")
        result = cursor.fetchone()

        print("Database Connected Successfully")
        print("Server Time:", result[0])

        cursor.close()
        conn.close()

    except Exception as e:
        print("Database Connection Failed")
        print(str(e))


if __name__ == "__main__":
    test_connection()