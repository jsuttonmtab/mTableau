import pandas as pd
import duckdb
import time
import shutil
from pathlib import Path
from db.connection import get_engine
from sqlalchemy import text
from utils.config import load_config, get_base_dir
import sys


# ── Paths ─────────────────────────────────────────────────────────────────────

DATA_DIR         = get_base_dir() / "data"
USAGE_PATH       = DATA_DIR / "usage.parquet"
BRIDGE_PATH      = DATA_DIR / "bridge.parquet"
STUDY_PATH       = DATA_DIR / "study.parquet"
USER_GROUP_PATH  = DATA_DIR / "user_group.parquet"

# Legacy path — kept so old installs can detect and migrate
EXTRACT_PATH     = DATA_DIR / "extract.parquet"


def _get_csv_paths():
    cfg         = load_config()
    upload_path = Path(cfg.get("MYSQL_UPLOAD_PATH", ""))
    return (
        upload_path / "usagefact_extract.csv",
        upload_path / "usagestudylinks_extract.csv",
    )


def extract_exists():
    """True when all four parquet files are present."""
    return (USAGE_PATH.exists() and BRIDGE_PATH.exists()
            and STUDY_PATH.exists() and USER_GROUP_PATH.exists())

extract_available = extract_exists

# ── Cancellation flag ─────────────────────────────────────────────────────────

_cancel_requested = False


def request_cancel():
    global _cancel_requested
    _cancel_requested = True


def reset_cancel():
    global _cancel_requested
    _cancel_requested = False


# ── Extract info ──────────────────────────────────────────────────────────────

def get_extract_info():
    if not extract_exists():
        if EXTRACT_PATH.exists():
            stat           = EXTRACT_PATH.stat()
            size_mb        = round(stat.st_size / 1024 / 1024, 2)
            last_refreshed = time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
            )
            try:
                con  = duckdb.connect()
                rows = con.execute(
                    f"SELECT COUNT(*) FROM read_parquet('{str(EXTRACT_PATH)}')"
                ).fetchone()[0]
                con.close()
            except Exception:
                rows = None
            return {
                "exists":         True,
                "legacy":         True,
                "last_refreshed": last_refreshed,
                "size_mb":        size_mb,
                "rows":           rows,
            }
        return {
            "exists":         False,
            "legacy":         False,
            "last_refreshed": None,
            "size_mb":        None,
            "rows":           None,
        }

    total_bytes = sum(
        p.stat().st_size for p in (USAGE_PATH, BRIDGE_PATH, STUDY_PATH, USER_GROUP_PATH)
    )
    size_mb = round(total_bytes / 1024 / 1024, 2)
    last_mtime = max(
        p.stat().st_mtime for p in (USAGE_PATH, BRIDGE_PATH, STUDY_PATH, USER_GROUP_PATH)
    )
    last_refreshed = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_mtime))

    try:
        con        = duckdb.connect()
        usage_rows = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{str(USAGE_PATH)}')"
        ).fetchone()[0]
        bridge_rows = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{str(BRIDGE_PATH)}')"
        ).fetchone()[0]
        con.close()
    except Exception:
        usage_rows  = None
        bridge_rows = None

    return {
        "exists":         True,
        "legacy":         False,
        "last_refreshed": last_refreshed,
        "size_mb":        size_mb,
        "usage_rows":     usage_rows,
        "bridge_rows":    bridge_rows,
        "rows":           usage_rows,
    }


# ── Build extract ─────────────────────────────────────────────────────────────

def build_extract(progress_callback=None):
    """
    Builds four parquet files using DuckDB's native MySQL extension.
    DuckDB reads MySQL tables directly in C++ — no Python row processing.
    """
    global _cancel_requested
    reset_cancel()

    cfg = load_config()
    db_host = cfg.get("DB_HOST", "localhost")
    db_port = cfg.get("DB_PORT", "3306")
    db_name = cfg.get("DB_NAME", "")
    db_user = cfg.get("DB_USER", "")
    db_pass = cfg.get("DB_PASSWORD", "")

    if not db_name or not db_user:
        if progress_callback:
            progress_callback("❌ Database not configured. Check Settings.", 0)
        return False, "Database not configured"

    # ── Pre-flight: test DB connection ────────────────────────────────────────
    try:
        test_engine = get_engine()
        with test_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        if progress_callback:
            progress_callback("✅ Database connection successful, starting...", 2)
    except Exception as e:
        if progress_callback:
            progress_callback(f"❌ Database connection failed: {str(e)}", 0)
        return False, str(e)

    start_time = time.time()

    def elapsed():
        secs       = int(time.time() - start_time)
        mins, secs = divmod(secs, 60)
        return f"{mins}m {secs}s"

    def cancelled():
        if _cancel_requested:
            if progress_callback:
                progress_callback("⚠️ Cancelled.", 0)
            return True
        return False

    temp_dir = DATA_DIR / "temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    temp_usage      = temp_dir / "usage.parquet"
    temp_bridge     = temp_dir / "bridge.parquet"
    temp_study      = temp_dir / "study.parquet"
    temp_user_group = temp_dir / "user_group.parquet"

    try:
        # ── Step 1: Connect DuckDB to MySQL directly ──────────────────────────
        if cancelled():
            return False, "Cancelled"
        if progress_callback:
            progress_callback("Step 1/5: Connecting DuckDB to MySQL...", 5)

        con = duckdb.connect()
        con.execute("SET memory_limit='8GB'")
        con.execute("SET threads=4")
        con.install_extension('mysql')
        con.load_extension('mysql')

        safe_pass = db_pass.replace("'", "\\'")

        con.execute(f"""
            ATTACH 'host={db_host} port={db_port} user={db_user} password={safe_pass} database={db_name}'
            AS mysql_db (TYPE mysql, READ_ONLY)
        """)

        if progress_callback:
            progress_callback(
                f"Step 1/5: DuckDB connected to MySQL ✅ ({elapsed()})", 8)

        # ── Step 2: Build usage.parquet directly from MySQL ───────────────────
        if cancelled():
            con.close()
            return False, "Cancelled"
        if progress_callback:
            progress_callback(
                f"Step 2/5: Building usage.parquet from MySQL... ({elapsed()})", 10)

        con.execute(f"""
            COPY (
                SELECT
                    f.USAGE_ID,
                    f.USER_ID,
                    TRIM(f.ACTION_TYPE)    AS ACTION_TYPE,
                    f.TABRUN_TS,
                    f.TABRUN_MY,
                    CAST(f.TABRUN_TS AS DATE) AS ACTION_DATE,
                    TRIM(u.USER_NAME)      AS USER_NAME,
                    TRIM(u.USER_EMAIL)     AS USER_EMAIL,
                    TRIM(c.CLIENT_NAME)    AS CLIENT_NAME
                FROM mysql_db.usagefact f
                LEFT JOIN (
                    SELECT uu.USER_ID,
                           FIRST(uu.USER_NAME)  AS USER_NAME,
                           FIRST(uu.USER_EMAIL) AS USER_EMAIL,
                           FIRST(uu.CLIENT_ID)  AS CLIENT_ID
                    FROM   mysql_db.usageuser uu
                    GROUP BY uu.USER_ID
                ) u ON f.USER_ID = u.USER_ID
                LEFT JOIN mysql_db.usageclient c ON u.CLIENT_ID = c.CLIENT_ID
            ) TO '{str(temp_usage)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        if progress_callback:
            progress_callback(
                f"Step 2/5: usage.parquet written ✅ ({elapsed()})", 40)

        # ── Step 3: Build bridge.parquet directly from MySQL ──────────────────
        if cancelled():
            con.close()
            return False, "Cancelled"
        if progress_callback:
            progress_callback(
                f"Step 3/5: Building bridge.parquet from MySQL... ({elapsed()})", 45)

        con.execute(f"""
            COPY (
                SELECT USAGE_ID, STUDY_ID
                FROM   mysql_db.usagestudylinks
            ) TO '{str(temp_bridge)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        if progress_callback:
            progress_callback(
                f"Step 3/5: bridge.parquet written ✅ ({elapsed()})", 65)

        # ── Step 4a: Build user_group.parquet ─────────────────────────────────
        if cancelled():
            con.close()
            return False, "Cancelled"
        if progress_callback:
            progress_callback(
                f"Step 4/5: Building user_group.parquet... ({elapsed()})", 70)

        con.execute(f"""
            COPY (
                SELECT
                    uu.USER_ID,
                    TRIM(uu.USER_NAME)    AS USER_NAME,
                    TRIM(uu.GROUP_NAME)   AS GROUP_NAME,
                    TRIM(c.CLIENT_NAME)   AS CLIENT_NAME
                FROM   mysql_db.usageuser uu
                JOIN   mysql_db.usageclient c ON c.CLIENT_ID = uu.CLIENT_ID
            ) TO '{str(temp_user_group)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        if progress_callback:
            progress_callback(
                f"Step 4/5: user_group.parquet written ✅ ({elapsed()})", 78)

        # ── Step 4b: Build study.parquet ──────────────────────────────────────
        if progress_callback:
            progress_callback(
                f"Step 4/5: Building study.parquet... ({elapsed()})", 80)

        con.execute(f"""
            COPY (
                SELECT
                    s.STUDY_ID,
                    TRIM(s.EXT_STUDY_ID) AS EXT_STUDY_ID,
                    TRIM(s.LONG_NAME)    AS LONG_NAME,
                    TRIM(e.STUDYID)      AS STUDYID,
                    e.STUDYYEAR
                FROM   mysql_db.usagestudy s
                LEFT JOIN mysql_db.study_metadata_enhanced e ON e.PKID = s.STUDY_ID
            ) TO '{str(temp_study)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        con.close()

        if progress_callback:
            progress_callback(
                f"Step 4/5: All parquet files built ✅ ({elapsed()})", 85)

        # ── Step 5: Atomic swap ───────────────────────────────────────────────
        if cancelled():
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False, "Cancelled"
        if progress_callback:
            progress_callback(f"Step 5/5: Finalising files... ({elapsed()})", 90)

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        for src, dst in (
            (temp_usage,      USAGE_PATH),
            (temp_bridge,     BRIDGE_PATH),
            (temp_study,      STUDY_PATH),
            (temp_user_group, USER_GROUP_PATH),
        ):
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))

        if EXTRACT_PATH.exists():
            EXTRACT_PATH.unlink()

        shutil.rmtree(temp_dir, ignore_errors=True)

        # ── Report final sizes ────────────────────────────────────────────────
        con2        = duckdb.connect()
        usage_rows  = con2.execute(
            f"SELECT COUNT(*) FROM read_parquet('{str(USAGE_PATH)}')"
        ).fetchone()[0]
        bridge_rows = con2.execute(
            f"SELECT COUNT(*) FROM read_parquet('{str(BRIDGE_PATH)}')"
        ).fetchone()[0]
        ug_rows = con2.execute(
            f"SELECT COUNT(*) FROM read_parquet('{str(USER_GROUP_PATH)}')"
        ).fetchone()[0]
        con2.close()

        total_mb = round(
            sum(p.stat().st_size for p in (USAGE_PATH, BRIDGE_PATH, STUDY_PATH, USER_GROUP_PATH))
            / 1024 / 1024, 1
        )

        if progress_callback:
            progress_callback(
                f"✅ Extract complete!  "
                f"{usage_rows:,} tab runs · {bridge_rows:,} study links · "
                f"{ug_rows:,} user-group memberships · "
                f"{total_mb} MB total.  Time: {elapsed()}.",
                100,
            )

        return True, usage_rows

    except Exception as e:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
        if progress_callback:
            progress_callback(f"❌ Error: {str(e)}", 0)
        return False, str(e)


# ── Load extract (legacy helper) ──────────────────────────────────────────────

def load_extract():
    if not USAGE_PATH.exists():
        return None
    return pd.read_parquet(USAGE_PATH)
