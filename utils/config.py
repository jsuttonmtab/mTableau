import copy
import json
import os
import threading
from pathlib import Path
import sys

def get_base_dir():
    return Path(__file__).parent.parent

def get_config_path(user_email=None):
    if user_email:
        return get_user_dir(user_email) / "config.json"
    return get_base_dir() / "config.json"

def get_user_dir(user_email):
    """Get per-user directory."""
    if not user_email:
        return get_base_dir() / "data"
    return get_base_dir() / "data" / "users" / user_email

def get_results_dir(user_email=None):
    """Get directory for saved query results."""
    if user_email:
        return get_user_dir(user_email) / "results"
    return get_base_dir() / "data" / "results"

_save_lock = threading.Lock()

DEFAULT_CONFIG = {
    "DB_HOST":           "",
    "DB_PORT":           "3306",
    "DB_NAME":           "",
    "DB_USER":           "",
    "DB_PASSWORD":       "",
    "worksheets":        ["Worksheet 1"],
}

# ── In-memory cache ───────────────────────────────────────────────────────────
# load_config() was being called on every Dash callback — with 4 worksheets
# and pattern-match ALL callbacks that means 15-20 disk reads per interaction.
# We cache by file mtime so disk is only read when config.json actually changes.

_cache      = {}  # {user_email: {data, mtime}} — None key = global
_cache_mtime = {}

def load_config(user_email=None):
    global _cache, _cache_mtime
    path = get_config_path(user_email)
    cache_key = user_email if user_email else "global"

    try:
        mtime = path.stat().st_mtime
        if cache_key in _cache and mtime == _cache_mtime.get(cache_key):
            return copy.deepcopy(_cache[cache_key])
        with open(path, "r") as f:
            data = json.load(f)
        _cache[cache_key]       = {**DEFAULT_CONFIG, **data}
        _cache_mtime[cache_key] = mtime
        return copy.deepcopy(_cache[cache_key])
    except FileNotFoundError:
        # New user or first load — return default
        if user_email:
            return DEFAULT_CONFIG.copy()
        # Fall back to .env for global config
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
            }
        except Exception as e2:
            print(f"[Config] ERROR reading .env: {e2}")
            return DEFAULT_CONFIG.copy()
    except Exception as e:
        print(f"[Config] ERROR loading config ({path}): {e}")
        return DEFAULT_CONFIG.copy()


def save_config(data, user_email=None):
    global _cache, _cache_mtime
    cache_key = user_email if user_email else "global"
    try:
        path = get_config_path(user_email)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique temp file per write + a lock: with gunicorn threads, two requests
        # can save at the same time, and a shared temp name would collide.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        with _save_lock:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            tmp.replace(path)
        # Update cache immediately
        _cache[cache_key]       = copy.deepcopy({**DEFAULT_CONFIG, **data})
        _cache_mtime[cache_key] = path.stat().st_mtime
        return True
    except Exception as e:
        print(f"[Config] ERROR saving config: {e}")
        return False