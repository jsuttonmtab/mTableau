#!/usr/bin/env python
"""Migrate global config/results to per-user storage (one-time operation)."""
import sys
import json
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config import load_config, save_config, get_user_dir, get_results_dir
from utils.auth import list_users

# Per-user keys to migrate from global config
PER_USER_KEYS = [
    "worksheets", "global_calculations", "ws_state", "ws_settings",
    "ws_last_run_state", "last_sql", "restore_complete"
]

def migrate(email, dry_run=False):
    """Migrate global state to per-user storage."""
    # Normalize email
    email = email.strip().lower()
    print(f"[Migrate] Email: {email}")

    # Check if user exists
    users = list_users()
    user_exists = any(u["email"] == email for u in users)
    if not user_exists:
        print(f"[Migrate] WARNING: {email} not found in data/users.json (continuing anyway)")

    # Load global config
    global_config = load_config(user_email=None)
    print(f"[Migrate] Loaded global config")

    # Load or create user config
    user_config = load_config(user_email=email)
    print(f"[Migrate] Loaded/created user config at {get_user_dir(email) / 'config.json'}")

    # Migrate per-user keys from global to user config
    migrated_keys = []
    for key in PER_USER_KEYS:
        if key in global_config:
            if key == "worksheets":
                # Merge worksheets: append those that don't exist
                existing = user_config.get("worksheets", [])
                new_worksheets = [w for w in global_config[key] if w not in existing]
                if new_worksheets:
                    user_config["worksheets"] = existing + new_worksheets
                    migrated_keys.append(f"{key} (+{len(new_worksheets)} new)")
            elif key in ["ws_state", "ws_settings", "global_calculations"]:
                # Merge dicts: add entries that don't exist by key
                existing = user_config.get(key, {})
                global_data = global_config[key]
                added_count = 0
                for subkey, value in global_data.items():
                    if subkey not in existing:
                        existing[subkey] = value
                        added_count += 1
                if added_count > 0:
                    user_config[key] = existing
                    migrated_keys.append(f"{key} (+{added_count} new entries)")
            else:
                # Simple copy (overwrite if not already set)
                if key not in user_config:
                    user_config[key] = global_config[key]
                    migrated_keys.append(key)

    print(f"[Migrate] Config keys to migrate: {', '.join(migrated_keys) if migrated_keys else 'none'}")

    # Migrate result files
    global_results_dir = get_results_dir(user_email=None)
    user_results_dir = get_results_dir(user_email=email)

    copied_files = []
    if global_results_dir.exists():
        for source_file in global_results_dir.glob("*"):
            if source_file.is_file():
                dest_file = user_results_dir / source_file.name
                if not dest_file.exists():  # Don't overwrite existing
                    if not dry_run:
                        user_results_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source_file, dest_file)
                    copied_files.append(source_file.name)

    print(f"[Migrate] Result files to copy: {', '.join(copied_files) if copied_files else 'none'}")

    # Save user config
    if not dry_run:
        save_config(user_config, user_email=email)
        print(f"[Migrate] Saved user config to {get_user_dir(email) / 'config.json'}")
    else:
        print(f"[Migrate] (DRY RUN - not saved)")

    print(f"[Migrate] Migration complete")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/migrate_to_user.py <email> [--dry-run]")
        sys.exit(1)

    email = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("[Migrate] DRY RUN MODE - no changes will be written")

    try:
        migrate(email, dry_run=dry_run)
    except Exception as e:
        print(f"[Migrate] ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
