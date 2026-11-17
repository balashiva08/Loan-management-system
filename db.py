
import mysql.connector

def get_connection():
    connection = mysql.connector.connect(
        host="localhost",
        user="root",
        password="Bala@2026Mysql!",
        database="loan_management"
    )
    return connection


if __name__ == "__main__":
    try:
        print("Testing MySQL connection...")

        conn = get_connection()
        print("MySQL connection successful!")

        conn.close()
        print("Connection closed.")

    except mysql.connector.Error as err:
        print("MySQL connection failed:", err)
