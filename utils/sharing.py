"""Sharing functionality: shared worksheets and calculations."""
import json
import threading
import time
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

def save_shared_calc(name, owner, formula, shared_with):
    """Save or update a shared calculation."""
    calcs = get_shared_calcs()

    # Check if name already exists (and owner is different)
    if name in calcs and calcs[name]["owner"] != owner:
        raise ValueError(f"Calculation '{name}' is already owned by {calcs[name]['owner']}")

    if shared_with:
        # Moving to shared library
        calcs[name] = {
            "owner": owner,
            "formula": formula,
            "shared_with": sorted(list(set(shared_with))),  # Deduplicate
            "updated_at": time.time()
        }
    else:
        # Removing from shared library (moving to personal)
        calcs.pop(name, None)

    _atomic_write(get_shared_calcs_path(), calcs)

def delete_shared_calc(name, owner):
    """Delete a shared calculation (owner or admin only)."""
    calcs = get_shared_calcs()
    if name in calcs and calcs[name]["owner"] == owner:
        calcs.pop(name, None)
        _atomic_write(get_shared_calcs_path(), calcs)
        return True
    return False

def get_available_calcs(user_email, personal_calcs):
    """Get available calcs for a user: personal + shared (where owner or shared_with)."""
    shared = get_shared_calcs()
    available = dict(personal_calcs)  # Personal wins on collision

    for name, calc_data in shared.items():
        if (calc_data["owner"] == user_email or
            user_email in calc_data.get("shared_with", [])):
            if name not in available:  # Personal takes precedence
                available[name] = {
                    "formula": calc_data["formula"],
                    "owner": calc_data["owner"],
                    "shared": True
                }

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

        # Add worksheet state
        if "ws_state" not in user_config:
            user_config["ws_state"] = {}
        ws_key = ws_name.replace(" ", "_")
        user_config["ws_state"][ws_key] = shared_ws["worksheet_state"]

        # Mark with shared_from for tracking
        if share_id:
            user_config["ws_state"][ws_key]["shared_from"] = {
                "share_id": share_id,
                "owner_email": shared_ws.get("from_email"),
                "source_worksheet": shared_ws.get("source_worksheet", shared_ws["worksheet_name"])
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
