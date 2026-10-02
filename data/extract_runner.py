"""
Run the extract build outside the web worker.

    python -m data.extract_runner          (started by the app; also works by hand)

The web app starts this as its own process, so a build that runs out of memory
only kills this process, not the site. Progress is written to
data/extract_status.json, which the app polls; cancelling is requested by
creating data/extract_cancel.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

if __package__ in (None, ""):                    # allow "python data/extract_runner.py"
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.extract import DATA_DIR, build_extract, request_cancel  # noqa: E402

STATUS_PATH = DATA_DIR / "extract_status.json"
CANCEL_PATH = DATA_DIR / "extract_cancel"
MAX_MESSAGES = 60


def read_status():
    try:
        with open(STATUS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def write_status(status):
    tmp = STATUS_PATH.with_name(f"{STATUS_PATH.name}.{os.getpid()}.tmp")
    with open(tmp, "w") as f:
        json.dump(status, f)
    tmp.replace(STATUS_PATH)


def run():
    """Build the extract, keeping extract_status.json up to date."""
    status = {"pid": os.getpid(), "started": time.time(),
              "finished": None, "done": False, "pct": 0, "messages": ["Starting extract..."]}
    write_status(status)
    try:
        CANCEL_PATH.unlink()
    except FileNotFoundError:
        pass

    stop = threading.Event()

    def watch_cancel():
        while not stop.wait(1.0):
            if CANCEL_PATH.exists():
                request_cancel()
                try:
                    CANCEL_PATH.unlink()
                except FileNotFoundError:
                    pass

    threading.Thread(target=watch_cancel, daemon=True).start()

    def progress(msg, pct):
        status["messages"] = (status["messages"] + [str(msg)])[-MAX_MESSAGES:]
        status["pct"] = pct
        if str(msg).startswith(("✅", "❌")):
            status["done"] = True
            status["finished"] = time.time()
        write_status(status)
        print(f"[Extract] {msg}", flush=True)

    try:
        build_extract(progress_callback=progress)
    except Exception as e:                       # report, don't leave it "running"
        progress(f"❌ Extract failed: {e}", status.get("pct", 0))
    finally:
        stop.set()
        if not status["done"]:
            progress("❌ Extract stopped before finishing.", status.get("pct", 0))


if __name__ == "__main__":
    run()
