from utils.config import load_config
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
import pandas as pd


def get_engine():
    cfg = load_config()
    password = quote_plus(cfg['DB_PASSWORD'])
    url = (f"mysql+pymysql://{cfg['DB_USER']}:{password}"
           f"@{cfg['DB_HOST']}:{cfg['DB_PORT']}/{cfg['DB_NAME']}")
    return create_engine(url)


def run_query(sql: str, params: dict = None) -> pd.DataFrame:
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params)


def test_connection():
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Database connection successful!")
    except Exception as e:
        print(f"❌ Connection failed: {e}")


if __name__ == "__main__":
    test_connection()