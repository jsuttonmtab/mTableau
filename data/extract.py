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
    use_csv_fallback = usagefact_csv.exists() and usagelinks_csv.exists()

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

        # Try to get row counts first to verify data availability
        try:
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
                    f"{len(studies):,} studies [OK] ({elapsed()})", 5
                )

            clients.to_csv(temp_dir / "clients.csv", index=False)
            users.to_csv(temp_dir / "users.csv",     index=False)
            studies.to_csv(temp_dir / "studies.csv", index=False)
            del clients, users, studies
        except Exception as e:
            if progress_callback:
                progress_callback(f"[WARNING] Could not fetch lookup tables: {e}", 5)
            if not use_csv_fallback:
                return False, f"Cannot fetch lookup tables and CSV fallback unavailable: {e}"

        # ── Step 2: Initialise DuckDB ─────────────────────────────────────────
        if cancelled():
            return False, "Cancelled"
        if progress_callback:
            progress_callback(f"Step 2/5: Initialising DuckDB... ({elapsed()})", 8)

        con = duckdb.connect(str(temp_dir / "work.duckdb"))
        con.execute("SET memory_limit='4GB'")
        con.execute("SET threads=4")

        # Setup MySQL extension for large table extraction (avoids timeouts)
        cfg = load_config()
        mysql_user = cfg.get("DB_USER", "")
        mysql_pwd = cfg.get("DB_PASSWORD", "")
        mysql_host = cfg.get("DB_HOST", "")
        mysql_port = cfg.get("DB_PORT", "3306")
        mysql_db = cfg.get("DB_NAME", "")

        try:
            con.execute("INSTALL mysql; LOAD mysql;")
            con.execute(f"""
                ATTACH 'host={mysql_host} port={mysql_port} database={mysql_db} charset=utf8mb4'
                AS mysql_db (
                    TYPE mysql,
                    USER '{mysql_user}',
                    PASSWORD '{mysql_pwd}',
                    READ_ONLY true
                )
            """)
        except Exception as e:
            print(f"[WARNING] MySQL extension not available, will use pandas fallback: {e}")
            mysql_attached = False
        else:
            mysql_attached = True

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

        # Build usage data - prefer MySQL extension, fallback to CSV
        con.execute("DROP TABLE IF EXISTS raw_facts")

        if mysql_attached:
            # Use MySQL directly - much faster for large tables
            con.execute("""
                CREATE TABLE raw_facts AS
                SELECT
                    USAGE_ID,
                    USER_ID,
                    ACTION_TYPE,
                    TABRUN_TS,
                    TABRUN_MY
                FROM mysql_db.usagefact
            """)
        elif use_csv_fallback:
            # Fall back to CSV if MySQL unavailable
            # Copy CSV locally to avoid network stalls (important for PyInstaller)
            if progress_callback:
                progress_callback(f"Copying {usagefact_csv.name} locally (this may take a minute)...", 12)
            local_usage_csv = temp_dir / usagefact_csv.name
            shutil.copy2(str(usagefact_csv), str(local_usage_csv))
            if progress_callback:
                progress_callback("Local copy complete, reading with pandas in chunks...", 15)

            # Create persistent DuckDB table for chunked inserts
            con.execute("""
                CREATE TABLE raw_facts (
                    USAGE_ID BIGINT,
                    USER_ID BIGINT,
                    ACTION_TYPE VARCHAR,
                    TABRUN_TS TIMESTAMP,
                    TABRUN_MY TIMESTAMP
                )
            """)

            # Read CSV in chunks to avoid memory overload (important for PyInstaller)
            for i, chunk in enumerate(pd.read_csv(
                str(local_usage_csv),
                header=None,
                names=['USAGE_ID', 'USER_ID', 'ACTION_TYPE', 'TABRUN_TS', 'TABRUN_MY'],
                chunksize=1_000_000,
                na_values=['\\N', '0000-00-00 00:00:00'],
                on_bad_lines='skip'
            )):
                # Register chunk as view and insert into table
                con.register('chunk_view', chunk)
                con.execute("INSERT INTO raw_facts SELECT * FROM chunk_view")
                if progress_callback:
                    progress_callback(
                        f"Loading usage data: {(i+1)*1_000_000:,} rows...", 15 + int(i * 0.5)
                    )
        else:
            con.close()
            return False, "MySQL extension unavailable and CSV fallback not available"

        if progress_callback:
            progress_callback(
                f"Step 3/5: usagefact loaded into DuckDB [OK] ({elapsed()})", 30)

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
                f"Step 3/5: usage.parquet written [OK] ({elapsed()})", 45)

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

        # Build bridge - prefer MySQL extension, fallback to CSV
        if mysql_attached:
            # Use MySQL directly
            con.execute(f"""
                COPY (
                    SELECT USAGE_ID, STUDY_ID
                    FROM mysql_db.usagestudylinks
                ) TO '{str(temp_bridge)}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """)
        elif use_csv_fallback:
            # Fall back to CSV if MySQL unavailable
            # Copy CSV locally to avoid network stalls (important for PyInstaller)
            if progress_callback:
                progress_callback(f"Copying {usagelinks_csv.name} locally (this may take a minute)...", 72)
            local_links_csv = temp_dir / usagelinks_csv.name
            shutil.copy2(str(usagelinks_csv), str(local_links_csv))
            if progress_callback:
                progress_callback("Local copy complete, reading with pandas in chunks...", 74)

            # Create persistent DuckDB table for chunked inserts
            con.execute("""
                CREATE TABLE bridge_facts (
                    USAGE_ID BIGINT,
                    STUDY_ID BIGINT
                )
            """)

            # Read CSV in chunks to avoid memory overload (important for PyInstaller)
            for i, chunk in enumerate(pd.read_csv(
                str(local_links_csv),
                header=None,
                names=['USAGE_ID', 'STUDY_ID'],
                chunksize=1_000_000,
                na_values=['\\N'],
                on_bad_lines='skip'
            )):
                # Register chunk as view and insert into table
                con.register('bridge_chunk_view', chunk)
                con.execute("INSERT INTO bridge_facts SELECT * FROM bridge_chunk_view")
                if progress_callback:
                    progress_callback(
                        f"Loading bridge data: {(i+1)*1_000_000:,} rows...", 74 + int(i * 0.25)
                    )

            # Write to parquet
            con.execute(f"""
                COPY (
                    SELECT USAGE_ID, STUDY_ID FROM bridge_facts
                ) TO '{str(temp_bridge)}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """)
        else:
            con.close()
            return False, "MySQL extension unavailable and CSV fallback not available"

        if progress_callback:
            progress_callback(
                f"Step 4/5: bridge.parquet written [OK] ({elapsed()})", 75)

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

        if mysql_attached:
            # Try DuckDB MySQL extension first (avoids timeout on large tables)
            try:
                con.execute(f"""
                    COPY (
                        SELECT USAGE_ID, TRIM(CAST(QMNEM AS VARCHAR)) AS QMNEM
                        FROM mysql_db.usageqmnem
                    ) TO '{str(temp_qmnem)}' (FORMAT PARQUET, COMPRESSION ZSTD)
                """)
            except Exception as e:
                # Fallback to chunked pandas if DuckDB MySQL extension fails
                print(f"[WARNING] DuckDB MySQL extension failed: {e}. Using chunked pandas fallback.")
                with engine.connect() as conn:
                    chunks = []
                    for chunk in pd.read_sql(
                        text("SELECT USAGE_ID, QMNEM FROM usageqmnem"), conn, chunksize=500000
                    ):
                        chunk['QMNEM'] = chunk['QMNEM'].astype(str).str.encode('ascii', errors='replace').str.decode('ascii')
                        chunks.append(chunk)
                qmnem_df = pd.concat(chunks, ignore_index=True)
                qmnem_df.to_parquet(str(temp_qmnem), compression='zstd', index=False)
        else:
            # Fallback to pandas if MySQL extension unavailable
            with engine.connect() as conn:
                qmnem_data = pd.read_sql(
                    text("SELECT USAGE_ID, QMNEM FROM usageqmnem"), conn
                )
            qmnem_data.to_parquet(temp_qmnem, compression="zstd", index=False)

        if progress_callback:
            progress_callback(
                f"Step 4b: qmnem.parquet written [OK] ({elapsed()})", 79)

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