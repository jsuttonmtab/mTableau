import json
from pathlib import Path
import sys

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent

def get_config_path():
    return get_base_dir() / "config.json"

DEFAULT_CONFIG = {
    "DB_HOST":           "",
    "DB_PORT":           "3306",
    "DB_NAME":           "",
    "DB_USER":           "",
    "DB_PASSWORD":       "",
    "MYSQL_UPLOAD_PATH": "",
    "worksheets":        ["Worksheet 1"],
}

# ── In-memory cache ───────────────────────────────────────────────────────────
# load_config() was being called on every Dash callback — with 4 worksheets
# and pattern-match ALL callbacks that means 15-20 disk reads per interaction.
# We cache by file mtime so disk is only read when config.json actually changes.

_cache      = None
_cache_mtime = None

def load_config():
    global _cache, _cache_mtime
    path = get_config_path()
    try:
        mtime = path.stat().st_mtime
        if _cache is not None and mtime == _cache_mtime:
            return dict(_cache)          # shallow copy — callers can read safely
        with open(path, "r") as f:
            data = json.load(f)
        _cache       = {**DEFAULT_CONFIG, **data}
        _cache_mtime = mtime
        return dict(_cache)
    except Exception as e:
        print(f"DEBUG load_config error: {e}")
        try:
            import os
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=get_base_dir() / ".env")
            return {
                "DB_HOST":           os.getenv("DB_HOST", ""),
                "DB_PORT":           os.getenv("DB_PORT", "3306"),
                "DB_NAME":           os.getenv("DB_NAME", ""),
                "DB_USER":           os.getenv("DB_USER", ""),
                "DB_PASSWORD":       os.getenv("DB_PASSWORD", ""),
                "MYSQL_UPLOAD_PATH": os.getenv("MYSQL_UPLOAD_PATH", ""),
            }
        except Exception as e2:
            print(f"DEBUG load_config .env error: {e2}")
            return DEFAULT_CONFIG.copy()


def save_config(data):
    global _cache, _cache_mtime
    try:
        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        # Update cache immediately — avoids a re-read on the very next load_config()
        _cache       = {**DEFAULT_CONFIG, **data}
        _cache_mtime = path.stat().st_mtime
        return True
    except Exception as e:
        print(f"DEBUG save_config ERROR: {e}")
        return False