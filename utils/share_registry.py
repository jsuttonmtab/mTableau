"""Tab sharing registry: tracks shared worksheet copies with per-recipient tracking."""
import json
import threading
import time
import uuid
from pathlib import Path
from utils.config import get_base_dir

_file_locks = {}
_lock_manager = threading.Lock()

def _get_lock(path):
    """Get a lock for atomic file writes."""
    with _lock_manager:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]

def _get_registry_path():
    """Get path to share registry."""
    return get_base_dir() / "data" / "shared" / "tab_shares.json"

def _atomic_read():
    """Read registry atomically."""
    lock = _get_lock(str(_get_registry_path()))
    with lock:
        path = _get_registry_path()
        if not path.exists():
            return []
        try:
            with open(path, "r") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []

def _atomic_write(records):
    """Write registry atomically."""
    lock = _get_lock(str(_get_registry_path()))
    with lock:
        path = _get_registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(records, f, indent=2)
        import os
        os.replace(temp_path, path)

def create_share(owner_email, owner_name, source_worksheet, recipient_email,
                 recipient_name, recipient_worksheet):
    """Create a share record. Returns share_id."""
    records = _atomic_read()

    # Check if record already exists for this (owner, source, recipient)
    for record in records:
        if (record["owner_email"] == owner_email and
            record["source_worksheet"] == source_worksheet and
            record["recipient_email"] == recipient_email):
            return record["share_id"]  # Already exists

    share_id = str(uuid.uuid4())
    record = {
        "share_id": share_id,
        "owner_email": owner_email,
        "owner_name": owner_name,
        "source_worksheet": source_worksheet,
        "recipient_email": recipient_email,
        "recipient_name": recipient_name,
        "recipient_worksheet": recipient_worksheet,
        "shared_at": time.time()
    }
    records.append(record)
    _atomic_write(records)
    return share_id

def get_shares_to(recipient_email, source_worksheet=None):
    """Get all shares received by a recipient, optionally filtered by source worksheet."""
    records = _atomic_read()
    results = []
    for record in records:
        if record["recipient_email"] == recipient_email:
            if source_worksheet is None or record["source_worksheet"] == source_worksheet:
                results.append(record)
    return results

def get_shares_from(owner_email, source_worksheet):
    """Get all shares of a source worksheet from its owner."""
    records = _atomic_read()
    results = []
    for record in records:
        if (record["owner_email"] == owner_email and
            record["source_worksheet"] == source_worksheet):
            results.append(record)
    return results

def delete_share_by_id(share_id):
    """Delete a share record by share_id."""
    records = _atomic_read()
    records = [r for r in records if r["share_id"] != share_id]
    _atomic_write(records)

def delete_shares_from_owner(owner_email, source_worksheet):
    """Delete all shares when source worksheet is deleted."""
    records = _atomic_read()
    records = [r for r in records if not (
        r["owner_email"] == owner_email and
        r["source_worksheet"] == source_worksheet
    )]
    _atomic_write(records)

def rename_source_worksheet(owner_email, old_name, new_name):
    """Update source_worksheet in all records when source is renamed."""
    records = _atomic_read()
    for record in records:
        if record["owner_email"] == owner_email and record["source_worksheet"] == old_name:
            record["source_worksheet"] = new_name
    _atomic_write(records)

def get_share_by_id(share_id):
    """Get a share record by share_id."""
    records = _atomic_read()
    for record in records:
        if record["share_id"] == share_id:
            return record
    return None
