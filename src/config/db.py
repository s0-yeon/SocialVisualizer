import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv("src/parquet/.env")

# .env 설정으로 분석용 MySQL DB에 연결해 커넥션 객체를 반환한다
def get_db_connection():
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )
    return conn