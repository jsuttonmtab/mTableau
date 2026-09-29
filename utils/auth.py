import json
import os
from pathlib import Path
from flask_login import UserMixin
import bcrypt

class User(UserMixin):
    def __init__(self, email, name, is_admin=False, must_change_password=False):
        self.id = email
        self.email = email
        self.name = name
        self.is_admin = is_admin
        self.must_change_password = must_change_password

def _get_users_file():
    """Get path to users.json file."""
    base_dir = Path(__file__).parent.parent
    return base_dir / "data" / "users.json"

def _hash_password(password):
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def _load_users():
    """Load users from JSON file."""
    users_file = _get_users_file()
    if users_file.exists():
        with open(users_file) as f:
            return json.load(f)
    return {}

def _save_users(users):
    """Save users to JSON file."""
    users_file = _get_users_file()
    users_file.parent.mkdir(parents=True, exist_ok=True)
    with open(users_file, 'w') as f:
        json.dump(users, f, indent=2)

def init_auth():
    """Initialize auth system — create default admin account if it doesn't exist."""
    users = _load_users()
    if not users:
        # Create default admin account
        admin_email = "admin@mtab.com"
        users[admin_email] = {
            "email": admin_email,
            "name": "Admin",
            "password_hash": _hash_password("admin"),
            "is_admin": True,
            "must_change_password": True
        }
        _save_users(users)
        print(f"[Auth] Created default admin account: {admin_email} / admin")

def authenticate(email, password):
    """Authenticate user by email and password. Returns User object or None."""
    email = email.strip().lower()
    users = _load_users()

    if email not in users:
        return None

    user_data = users[email]
    stored_hash = user_data.get("password_hash", "")

    try:
        if bcrypt.checkpw(password.encode(), stored_hash.encode()):
            return User(
                email=email,
                name=user_data.get("name", email),
                is_admin=user_data.get("is_admin", False),
                must_change_password=user_data.get("must_change_password", False)
            )
    except ValueError:
        print(f"[Auth] unusable hash for {email}")

    return None

def get_user(email):
    """Get user by email. Returns User object or None."""
    users = _load_users()
    if email not in users:
        return None

    user_data = users[email]
    return User(
        email=email,
        name=user_data.get("name", email),
        is_admin=user_data.get("is_admin", False),
        must_change_password=user_data.get("must_change_password", False)
    )

def must_change_password(email):
    """Check if user must change password."""
    users = _load_users()
    if email not in users:
        return False
    return users[email].get("must_change_password", False)

def change_password(email, new_password):
    """Change user password and clear must_change_password flag."""
    email = email.strip().lower()
    users = _load_users()
    if email not in users:
        return False

    users[email]["password_hash"] = _hash_password(new_password)
    users[email]["must_change_password"] = False
    _save_users(users)
    return True

def add_user(email, name, password, is_admin=False):
    """Add new user."""
    email = email.strip().lower()
    users = _load_users()
    if email in users:
        return False  # User already exists

    users[email] = {
        "email": email,
        "name": name,
        "password_hash": _hash_password(password),
        "is_admin": is_admin,
        "must_change_password": True  # New users must change password
    }
    _save_users(users)
    return True

def delete_user(email):
    """Delete user by email."""
    users = _load_users()
    if email not in users:
        return False

    del users[email]
    _save_users(users)
    return True

def list_users():
    """List all users."""
    users = _load_users()
    return [
        {
            "email": email,
            "name": data.get("name", email),
            "is_admin": data.get("is_admin", False),
            "must_change_password": data.get("must_change_password", False)
        }
        for email, data in users.items()
    ]

def reset_password(email, new_password):
    """Reset user password and set must_change_password flag."""
    email = email.strip().lower()
    users = _load_users()
    if email not in users:
        return False

    users[email]["password_hash"] = _hash_password(new_password)
    users[email]["must_change_password"] = True
    _save_users(users)
    return True
