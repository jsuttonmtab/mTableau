"""
Desktop launcher for mTableau: runs the app on a local port and shows it in a
native window (pywebview). This is the script PyInstaller builds into
mTableau.exe:

    py -3.12 -m PyInstaller ... --windowed --name "mTableau" run.py
"""
import socket
import sys
import threading
import time

import webview

from app import app


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(port, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main():
    port = _free_port()
    server = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False),
        daemon=True)
    server.start()
    if not _wait_until_up(port):
        print("mTableau server did not start", file=sys.stderr)
        sys.exit(1)
    webview.create_window("mTableau", f"http://127.0.0.1:{port}",
                          width=1600, height=950, min_size=(1000, 650))
    webview.start()          # returns when the window is closed; the server thread ends with it


if __name__ == "__main__":
    main()
