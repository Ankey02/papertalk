"""Password hashing and the "who is logged in" check."""
import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request

from .db import get_db

ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS)
    return hmac.compare_digest(digest.hex(), digest_hex)


def get_user(request: Request):
    """Return the logged-in user row, or None."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with get_db() as conn:
        return conn.execute(
            "SELECT id, name, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()


def require_user(request: Request):
    """FastAPI dependency for API routes: 401 when not logged in."""
    user = get_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in again.")
    return user
