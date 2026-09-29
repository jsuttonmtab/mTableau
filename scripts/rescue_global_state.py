"""
One-time repair: after per-user isolation, query runs kept saving worksheet
layouts (ws_state) and results to the GLOBAL config/results instead of the
user's own. This copies them back into each user's storage.

Usage (from the app directory, venv active):
  python scripts/rescue_global_state.py                     # dry run, report only
  python scripts/rescue_global_state.py --apply             # copy only what users are MISSING
  python scripts/rescue_global_state.py --apply --prefer-global jsutton@mtab.com
        # also overwrite that user's DIFFERING tabs with the global version

Never touches received (shared) tabs. Never deletes anything. Back up data/ first.
"""
import argparse, json, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.config import load_config, save_config, get_base_dir, get_results_dir  # noqa: E402

RESULT_EXTS = [".parquet", ".meta.json", ".summary.parquet"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--prefer-global", action="append", default=[],
                    help="email whose differing tabs should take the global version")
    args = ap.parse_args()
    prefer = {e.strip().lower() for e in args.prefer_global}

    global_cfg   = load_config()
    global_state = global_cfg.get("ws_state", {})
    global_res   = get_results_dir(None)

    users_dir = get_base_dir() / "data" / "users"
    emails = sorted(p.name for p in users_dir.iterdir() if (p / "config.json").exists()) \
        if users_dir.exists() else []
    if not emails:
        print("No per-user configs found.")
        return

    for email in emails:
        cfg   = load_config(user_email=email)
        state = cfg.setdefault("ws_state", {})
        res   = get_results_dir(email)
        changed = False
        print(f"\n== {email} ==")
        for name in cfg.get("worksheets", []):
            key = name.replace(" ", "_")
            mine = state.get(key)
            if mine and mine.get("shared_from"):
                print(f"  {name!r}: received tab, skipped")
                continue
            theirs = global_state.get(key)
            if not theirs:
                print(f"  {name!r}: not in global, nothing to do")
                continue
            if mine == theirs:
                print(f"  {name!r}: same")
                continue
            status = "MISSING" if not mine else "DIFFERS"
            take = status == "MISSING" or email.lower() in prefer
            print(f"  {name!r}: {status}" + (" -> copy global" if take else " (kept; use --prefer-global to take global)"))
            if take and args.apply:
                state[key] = json.loads(json.dumps(theirs))
                changed = True
                res.mkdir(parents=True, exist_ok=True)
                for ext in RESULT_EXTS:
                    src = global_res / f"{key}{ext}"
                    dst = res / f"{key}{ext}"
                    if src.exists() and (status == "DIFFERS" or not dst.exists()):
                        shutil.copy2(src, dst)
                        print(f"      copied result {src.name}")
        if changed:
            save_config(cfg, user_email=email)
            print("  saved.")
    if not args.apply:
        print("\nDry run only. Re-run with --apply to make changes.")


if __name__ == "__main__":
    main()
