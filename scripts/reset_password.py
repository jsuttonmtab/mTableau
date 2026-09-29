#!/usr/bin/env python
"""Reset a user's password via command line."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.auth import reset_password

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/reset_password.py <email> <password>")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    if reset_password(email, password):
        print(f"[Auth] Password reset for {email}, must_change_password=True")
    else:
        print(f"[Auth] User {email} not found")
        sys.exit(1)
