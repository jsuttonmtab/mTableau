"""Sharing functionality: shared worksheets and calculations."""
import json
import threading
import time
import copy
from pathlib import Path
from utils.config import get_base_dir, get_user_dir

# Thread-safe file writes
_file_locks = {}
_lock_manager = threading.Lock()

def _get_lock(path):
    """Get a lock for atomic file writes."""
    with _lock_manager:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]

def _atomic_write(path, data):
    """Atomically write JSON to a file."""
    lock = _get_lock(str(path))
    with lock:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)
        import os
        os.replace(temp_path, path)

def _atomic_read(path):
    """Atomically read JSON from a file."""
    lock = _get_lock(str(path))
    with lock:
        path = Path(path)
        if not path.exists():
            return {}
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

# ── Inbox management (shared worksheets) ──────────────────────────────────
def get_inbox_path(user_email):
    """Get path to user's inbox."""
    return get_user_dir(user_email) / "inbox.json"

def add_to_inbox(user_email, share_id, from_email, from_name, worksheet_name,
                 worksheet_state, calcs, source_worksheet=None):
    """Add a shared worksheet to user's inbox."""
    inbox = _atomic_read(get_inbox_path(user_email))
    if "worksheets" not in inbox:
        inbox["worksheets"] = []

    inbox["worksheets"].append({
        "share_id": share_id,
        "from_email": from_email,
        "from_name": from_name,
        "sent_at": time.time(),
        "worksheet_name": worksheet_name,
        "worksheet_state": worksheet_state,
        "calcs": calcs,
        "source_worksheet": source_worksheet or worksheet_name
    })
    _atomic_write(get_inbox_path(user_email), inbox)

def get_inbox(user_email):
    """Get user's inbox."""
    return _atomic_read(get_inbox_path(user_email))

def clear_inbox(user_email):
    """Clear user's inbox."""
    _atomic_write(get_inbox_path(user_email), {})

# ── Shared calculation library ─────────────────────────────────────────────
def get_shared_calcs_path():
    """Get path to shared calculations library."""
    return get_base_dir() / "data" / "shared" / "calculations.json"

def get_shared_calcs():
    """Get all shared calculations."""
    return _atomic_read(get_shared_calcs_path())

# Serialises read-modify-write of the calc library (the file helpers lock each
# read and write separately; their lock isn't re-entrant).
_calc_lib_lock = threading.Lock()


def _calc_defn(entry):
    """Calculation definition from a library entry (older entries stored only a formula)."""
    if isinstance(entry.get("defn"), dict):
        return dict(entry["defn"])
    return {"type": "formula", "formula": entry.get("formula", "")}


def share_calc(name, owner, owner_name, defn, shared_with):
    """
    Share (or update the share of) the owner's calculation `name` with the given
    users. An empty shared_with removes it from the library. Names are unique in
    the library: another owner's shared calc with the same name raises ValueError.
    """
    with _calc_lib_lock:
        calcs = get_shared_calcs()
        existing = calcs.get(name)
        if existing and existing.get("owner") != owner:
            raise ValueError(f"'{name}' is already shared by "
                             f"{existing.get('owner_name') or existing.get('owner')}. "
                             f"Choose a different name to share it.")
        recipients = sorted(set(e for e in (shared_with or []) if e and e != owner))
        if recipients:
            clean = {k: v for k, v in (defn or {}).items() if not str(k).startswith("_")}
            calcs[name] = {"owner": owner, "owner_name": owner_name or owner, "defn": clean,
                           "shared_with": recipients, "updated_at": time.time()}
        else:
            calcs.pop(name, None)
        _atomic_write(get_shared_calcs_path(), calcs)


def unshare_calc(name, owner):
    """Remove the owner's calculation from the library (deleted or renamed)."""
    with _calc_lib_lock:
        calcs = get_shared_calcs()
        if name in calcs and calcs[name].get("owner") == owner:
            calcs.pop(name)
            _atomic_write(get_shared_calcs_path(), calcs)


def calc_shared_with(name, owner):
    """Who the owner's calculation `name` is shared with ([] if not shared)."""
    entry = get_shared_calcs().get(name)
    if entry and entry.get("owner") == owner:
        return list(entry.get("shared_with", []))
    return []


def get_available_calcs(user_email, personal_calcs):
    """
    The user's calculations plus those shared with them. Shared-in entries carry
    "_shared_by" (owner's display name) and "_owner" (email), are read-only, and
    are never saved into the user's own config. A personal calc with the same
    name takes precedence.
    """
    available = dict(personal_calcs or {})
    for name, entry in get_shared_calcs().items():
        if entry.get("owner") == user_email or name in available:
            continue
        if user_email in entry.get("shared_with", []):
            defn = _calc_defn(entry)
            defn["_shared_by"] = entry.get("owner_name") or entry.get("owner")
            defn["_owner"] = entry.get("owner")
            available[name] = defn
    return available


def merge_inbox_to_config(user_email, user_config):
    """Merge inbox worksheets into user's config, handling collisions. Idempotent: checks share_id."""
    from utils.share_registry import get_share_by_id

    inbox = get_inbox(user_email)
    if "worksheets" not in inbox or not inbox["worksheets"]:
        return user_config, []

    alerts = []
    for shared_ws in inbox["worksheets"]:
        share_id = shared_ws.get("share_id")

        # Skip if already merged (check if share_id exists in any worksheet's shared_from)
        if share_id:
            already_merged = False
            for ws_key, ws_state in user_config.get("ws_state", {}).items():
                if ws_state.get("shared_from", {}).get("share_id") == share_id:
                    already_merged = True
                    break
            if already_merged:
                continue

        from_name = shared_ws.get("from_name", shared_ws["from_email"])
        ws_name = shared_ws["worksheet_name"]

        # Handle worksheet name collision
        if ws_name in user_config.get("worksheets", []):
            ws_name = f"{ws_name} (from {from_name})"

        if "worksheets" not in user_config:
            user_config["worksheets"] = []
        user_config["worksheets"].append(ws_name)

        # Store only shared_from metadata - worksheet definition loads live from owner
        if "ws_state" not in user_config:
            user_config["ws_state"] = {}
        ws_key = ws_name.replace(" ", "_")

        # Received tabs are live references, not copies
        user_config["ws_state"][ws_key] = {
            "shared_from": {
                "share_id": share_id,
                "owner_email": shared_ws.get("from_email"),
                "source_worksheet": shared_ws.get("source_worksheet", shared_ws["worksheet_name"])
            }
        }

        # Merge calculations with collision handling
        if "global_calculations" not in user_config:
            user_config["global_calculations"] = {}

        for calc_name, formula in shared_ws.get("calcs", {}).items():
            if calc_name in user_config["global_calculations"]:
                if user_config["global_calculations"][calc_name] == formula:
                    # Same formula, skip
                    continue
                else:
                    # Different formula, rename
                    from_email = shared_ws["from_email"].split("@")[0]
                    new_name = f"{calc_name}_from_{from_email}"
                    user_config["global_calculations"][new_name] = formula
                    # Update worksheet to use renamed calc
                    ws_state = user_config["ws_state"][ws_key]
                    # Simple text replacement in filters
                    for key in ["rows", "cols", "filters", "field_filters"]:
                        if key in ws_state and isinstance(ws_state[key], str):
                            ws_state[key] = ws_state[key].replace(calc_name, new_name)
            else:
                user_config["global_calculations"][calc_name] = formula

        alerts.append(f"{from_name} shared worksheet '{shared_ws['worksheet_name']}'")

    return user_config, alerts


def prune_revoked_shares(user_email, user_config):
    """
    Remove received tabs whose share record no longer exists: the owner removed
    this user's access, or deleted the source tab. Returns
    (config, alerts, changed). Also deletes the recipient's saved results for
    those tabs.
    """
    from utils.share_registry import get_share_by_id
    from utils.config import get_results_dir

    ws_state = user_config.get("ws_state", {})
    keep, alerts, removed = [], [], []
    for name in user_config.get("worksheets", []):
        key = name.replace(" ", "_")
        sf = (ws_state.get(key) or {}).get("shared_from") or {}
        if sf.get("share_id") and get_share_by_id(sf["share_id"]) is None:
            removed.append((name, key))
            alerts.append(f"'{name}' is no longer shared with you.")
        else:
            keep.append(name)
    if not removed:
        return user_config, [], False
    user_config["worksheets"] = keep or ["Worksheet 1"]
    results_dir = get_results_dir(user_email)
    for name, key in removed:
        ws_state.pop(key, None)
        user_config.get("ws_settings", {}).pop(key, None)
        for ext in (".parquet", ".meta.json", ".summary.parquet"):
            try:
                (results_dir / f"{key}{ext}").unlink()
            except FileNotFoundError:
                pass
    return user_config, alerts, True
