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
QMNEM_PATH       = DATA_DIR / "qmnem.parquet"

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
    """True when all five parquet files are present."""
    return (USAGE_PATH.exists() and BRIDGE_PATH.exists()
            and STUDY_PATH.exists() and USER_GROUP_PATH.exists()
            and QMNEM_PATH.exists())


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
        # Fall back to legacy single-file check for old installs
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

    # All five files present — report combined stats
    total_bytes = sum(
        p.stat().st_size for p in (USAGE_PATH, BRIDGE_PATH, STUDY_PATH, USER_GROUP_PATH, QMNEM_PATH)
    )
    size_mb = round(total_bytes / 1024 / 1024, 2)

    # Use the most recent mtime as the refresh timestamp
    last_mtime = max(
        p.stat().st_mtime for p in (USAGE_PATH, BRIDGE_PATH, STUDY_PATH, USER_GROUP_PATH, QMNEM_PATH)
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
        "usage_rows":     usage_rows,   # unique tab runs
        "bridge_rows":    bridge_rows,  # tab-run × study links
        # keep a generic "rows" key for any code that reads it generically
        "rows":           usage_rows,
    }


# ── Build extract ─────────────────────────────────────────────────────────────

def build_extract(progress_callback=None):
    """
    Replaces the single 3 GB parquet with three lean files:

        usage.parquet   — grain: USAGE_ID  (~47 M rows, all user/date dims)
        bridge.parquet  — grain: (USAGE_ID, STUDY_ID)  (~230 M rows, ints only)
        study.parquet   — grain: STUDY_ID  (small lookup)

    Query engine joins them at query time via DuckDB, so every existing measure
    and every LOD calculation continues to work unchanged.
    """
    global _cancel_requested
    reset_cancel()

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

    usagefact_csv, usagelinks_csv = _get_csv_paths()

    if not usagefact_csv.exists():
        if progress_callback:
            progress_callback(
                f"❌ Missing: {usagefact_csv}. Please run MySQL export first.", 0)
        return False, "Missing usagefact CSV"

    if not usagelinks_csv.exists():
        if progress_callback:
            progress_callback(
                f"❌ Missing: {usagelinks_csv}. Please run MySQL export first.", 0)
        return False, "Missing usagestudylinks CSV"

    # ── Temp workspace ────────────────────────────────────────────────────────
    temp_dir = DATA_DIR / "temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Write to temp paths first; swap to final on success so a failed
    # mid-run extract never leaves the app with partial files.
    temp_usage      = temp_dir / "usage.parquet"
    temp_bridge     = temp_dir / "bridge.parquet"
    temp_study      = temp_dir / "study.parquet"
    temp_user_group = temp_dir / "user_group.parquet"
    temp_qmnem      = temp_dir / "qmnem.parquet"

    try:
        engine = get_engine()

        # ── Step 1: Fetch lookup tables from MySQL ────────────────────────────
        if cancelled():
            return False, "Cancelled"
        if progress_callback:
            progress_callback("Step 1/5: Fetching lookup tables from MySQL...", 2)

        with engine.connect() as conn:
            clients = pd.read_sql(
                text("SELECT CLIENT_ID, CLIENT_NAME FROM usageclient"), conn
            )
            users = pd.read_sql(
                text("""
                    SELECT DISTINCT
                           uu.USER_ID,
                           uu.USER_NAME,
                           uu.USER_EMAIL,
                           uu.CLIENT_ID,
                           uu.GROUP_NAME,
                           c.CLIENT_NAME
                    FROM   usageuser uu
                    JOIN   usageclient c ON c.CLIENT_ID = uu.CLIENT_ID
                """), conn
            )
            studies = pd.read_sql(
                text("""
                    SELECT s.STUDY_ID,
                           s.EXT_STUDY_ID,
                           s.LONG_NAME,
                           e.STUDYID,
                           e.STUDYYEAR
                    FROM   usagestudy s
                    LEFT JOIN study_metadata_enhanced e ON e.PKID = s.STUDY_ID
                """), conn
            )

        if progress_callback:
            progress_callback(
                f"Step 1/5: {len(clients):,} clients, {len(users):,} user-group memberships, "
                f"{len(studies):,} studies ✅ ({elapsed()})", 5
            )

        clients.to_csv(temp_dir / "clients.csv", index=False)
        users.to_csv(temp_dir / "users.csv",     index=False)
        studies.to_csv(temp_dir / "studies.csv", index=False)
        del clients, users, studies

        # ── Step 2: Initialise DuckDB ─────────────────────────────────────────
        if cancelled():
            return False, "Cancelled"
        if progress_callback:
            progress_callback(f"Step 2/5: Initialising DuckDB... ({elapsed()})", 8)

        con = duckdb.connect(str(temp_dir / "work.duckdb"))
        con.execute("SET memory_limit='8GB'")
        con.execute("SET threads=4")

        # Load lookup tables
        con.execute(f"CREATE TABLE clients AS SELECT * FROM read_csv_auto('{str(temp_dir / 'clients.csv')}')")
        con.execute(f"CREATE TABLE users   AS SELECT * FROM read_csv_auto('{str(temp_dir / 'users.csv')}')")
        con.execute(f"CREATE TABLE studies AS SELECT * FROM read_csv_auto('{str(temp_dir / 'studies.csv')}')")

        # ── Step 3: Build usage.parquet  (grain: USAGE_ID) ───────────────────
        #
        #   Contains every per-tab-run dimension: user, client, action, dates.
        #   No study columns here — those live in study.parquet and are joined
        #   at query time via bridge.parquet.
        #
        if cancelled():
            con.close()
            return False, "Cancelled"
        if progress_callback:
            progress_callback(
                f"Step 3/5: Building usage.parquet (USAGE_ID grain)... ({elapsed()})", 10)

        # Two-pass approach: stage raw_facts first with proper type casting and
        # timestamp cleaning, then join to users/clients for the final parquet.
        con.execute("DROP TABLE IF EXISTS raw_facts")
        con.execute(f"""
            CREATE TABLE raw_facts AS
            SELECT
                column0::BIGINT  AS USAGE_ID,
                column1::BIGINT  AS USER_ID,
                column2::VARCHAR AS ACTION_TYPE,
                CASE WHEN column3 IN ('0000-00-00 00:00:00', '\\N', '')
                     THEN NULL ELSE TRY_CAST(column3 AS TIMESTAMP) END AS TABRUN_TS,
                CASE WHEN column4 IN ('0000-00-00 00:00:00', '\\N', '')
                     THEN NULL ELSE TRY_CAST(column4 AS TIMESTAMP) END AS TABRUN_MY
            FROM read_csv('{str(usagefact_csv)}',
                header=false, nullstr='\\N',
                all_varchar=true, ignore_errors=true)
        """)

        if progress_callback:
            progress_callback(
                f"Step 3/5: usagefact loaded into DuckDB ✅ ({elapsed()})", 30)

        con.execute(f"""
            COPY (
                SELECT
                    f.USAGE_ID,
                    f.USER_ID,
                    regexp_replace(TRIM(f.ACTION_TYPE), '\r', '')  AS ACTION_TYPE,
                    f.TABRUN_TS,
                    f.TABRUN_MY,
                    DATE(f.TABRUN_TS)    AS ACTION_DATE,
                    regexp_replace(TRIM(u.USER_NAME),   '\r', '')  AS USER_NAME,
                    regexp_replace(TRIM(u.USER_EMAIL),  '\r', '')  AS USER_EMAIL,
                    regexp_replace(TRIM(c.CLIENT_NAME), '\r', '')  AS CLIENT_NAME
                FROM      raw_facts f
                -- Deduplicate users to one row per USER_ID for this join
                -- (GROUP_NAME lives in user_group.parquet instead)
                LEFT JOIN (
                    SELECT USER_ID,
                           FIRST(USER_NAME) AS USER_NAME,
                           FIRST(USER_EMAIL) AS USER_EMAIL,
                           FIRST(CLIENT_ID) AS CLIENT_ID
                    FROM   users
                    GROUP BY USER_ID
                )         u ON f.USER_ID   = u.USER_ID
                LEFT JOIN clients c ON u.CLIENT_ID = c.CLIENT_ID
            ) TO '{str(temp_usage)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        if progress_callback:
            progress_callback(
                f"Step 3/5: usage.parquet written ✅ ({elapsed()})", 45)

        # ── Step 4: Build bridge.parquet  (grain: USAGE_ID × STUDY_ID) ───────
        #
        #   Pure integer join table — ~230 M rows but only 2 columns.
        #   ZSTD compresses integer sequences very aggressively (~50 MB result).
        #
        if cancelled():
            con.close()
            return False, "Cancelled"
        if progress_callback:
            progress_callback(
                f"Step 4/5: Building bridge.parquet (USAGE_ID × STUDY_ID)... ({elapsed()})", 48)

        con.execute(f"""
            COPY (
                SELECT column0::BIGINT AS USAGE_ID,
                       column1::BIGINT AS STUDY_ID
                FROM read_csv('{str(usagelinks_csv)}',
                    header=false, nullstr='\\N',
                    all_varchar=true, ignore_errors=true)
            ) TO '{str(temp_bridge)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        if progress_callback:
            progress_callback(
                f"Step 4/5: bridge.parquet written ✅ ({elapsed()})", 75)

        # ── Step 4b: Build user_group.parquet  (grain: USER_ID × GROUP_NAME) ──
        #
        #   One row per user-group membership.  USER_ID is the invisible join key
        #   back to usage.parquet.  USER_NAME / GROUP_NAME / CLIENT_NAME are the
        #   front-end display columns.  A user in multiple groups or clients
        #   gets multiple rows here — fanout is intentional and correct.
        #
        con.execute(f"""
            COPY (
                SELECT
                    USER_ID,
                    regexp_replace(TRIM(USER_NAME),   '\r', '') AS USER_NAME,
                    regexp_replace(TRIM(GROUP_NAME),  '\r', '') AS GROUP_NAME,
                    regexp_replace(TRIM(CLIENT_NAME), '\r', '') AS CLIENT_NAME
                FROM users
            ) TO '{str(temp_user_group)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        if progress_callback:
            progress_callback(
                f"Step 4/5: user_group.parquet written ✅ ({elapsed()})", 78)

        # ── Step 4b: Build qmnem.parquet  (grain: USAGE_ID) ────────────────────
        #
        #   Simple USAGE_ID × QMNEM join table. Loaded from MySQL usageqmnem.
        #
        if cancelled():
            con.close()
            return False, "Cancelled"

        with engine.connect() as conn:
            qmnem_data = pd.read_sql(
                text("SELECT USAGE_ID, QMNEM FROM usageqmnem"), conn
            )

        qmnem_data.to_parquet(temp_qmnem, compression="zstd", index=False)

        if progress_callback:
            progress_callback(
                f"Step 4b: qmnem.parquet written ✅ ({elapsed()})", 79)

        # ── Step 4c: Build study.parquet  (grain: STUDY_ID) ──────────────────
        con.execute(f"""
            COPY (
                SELECT
                    STUDY_ID,
                    regexp_replace(TRIM(EXT_STUDY_ID), '\r', '') AS EXT_STUDY_ID,
                    regexp_replace(TRIM(LONG_NAME),    '\r', '') AS LONG_NAME,
                    regexp_replace(TRIM(STUDYID),      '\r', '') AS STUDYID,
                    STUDYYEAR
                FROM studies
            ) TO '{str(temp_study)}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """)

        con.close()

        # ── Step 5: Atomic swap ───────────────────────────────────────────────
        #
        #   Only replace live files after all three temp files are confirmed
        #   written.  A cancelled or errored run never corrupts the live data.
        #
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
            (temp_qmnem,      QMNEM_PATH),
        ):
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))

        # Remove legacy single-file extract if present so old code paths
        # don't silently fall back to stale data.
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
            sum(p.stat().st_size for p in (USAGE_PATH, BRIDGE_PATH, STUDY_PATH, USER_GROUP_PATH, QMNEM_PATH))
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


# ── Load extract (legacy helper — kept for any callers that used it) ──────────

def load_extract():
    """
    Returns the usage parquet as a DataFrame.
    Callers that need study dims should use the query engine instead.
    """
    if not USAGE_PATH.exists():
        return None
    return pd.read_parquet(USAGE_PATH)