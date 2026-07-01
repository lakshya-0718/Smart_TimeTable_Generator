"""
core/security.py — Pure cryptographic utilities.

Responsibilities:
  - Password hashing and verification (passlib / bcrypt).
  - JWT access-token creation and decoding (python-jose / HS256).

Design rules:
  - NO FastAPI imports here.  No Request, no Depends, no HTTPException.
    This file is pure Python so it is independently testable without
    spinning up a FastAPI app.
  - NO database imports.  Security primitives know nothing about users
    or sessions.
  - All settings are read from `get_settings()` at call-time (not at
    import-time) so the lru_cache singleton is always used and tests
    can override settings via environment variables before the first call.

JWT payload structure:
  {
    "sub":  "<user_uuid_as_str>",     # standard JWT subject claim
    "role": "ADMIN | FACULTY | TA",   # used by deps.py for role guards
    "exp":  <unix_timestamp>          # set by create_access_token
  }

The payload intentionally excludes email, full_name, and is_active.
- Email can change (admin updates it) → stale claims would be incorrect.
- is_active must be checked against the DB on every request anyway
  (a deactivated user must be denied even with a valid token).
- Keeping the payload small reduces token size on every HTTP request.
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

# ── Password hashing ──────────────────────────────────────────────────────────

# bcrypt is the only scheme.  deprecated="auto" means passlib will
# automatically re-hash any password stored with an old scheme if one
# is introduced in the future (safe forward-compat pattern).
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(plain_password: str) -> str:
    """
    Return the bcrypt hash of `plain_password`.

    Called by the admin-facing user-creation service.
    The returned string is safe to store in the `users.hashed_password` column.
    """
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Return True iff `plain_password` matches the stored `hashed_password`.

    Called during login.  bcrypt's constant-time comparison prevents
    timing attacks; passlib handles this transparently.
    """
    return _pwd_context.verify(plain_password, hashed_password)


# ── JWT tokens ────────────────────────────────────────────────────────────────

def create_access_token(
    subject: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject:       The user's UUID as a string.  Stored in the "sub" claim.
        role:          The user's role string ("ADMIN", "FACULTY", "TA").
        expires_delta: Optional override for token lifetime.  If omitted,
                       uses JWT_ACCESS_TOKEN_EXPIRE_MINUTES from settings.

    Returns:
        A compact, URL-safe JWT string (header.payload.signature).

    The expiry is computed from UTC now, not local time, to avoid timezone
    bugs on servers with non-UTC system clocks.
    """
    settings = get_settings()

    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    expire = datetime.now(timezone.utc) + expires_delta

    payload: dict = {
        "sub": subject,       # user UUID string
        "role": role,         # role string for dep guards
        "exp": expire,        # jose encodes datetime → unix timestamp
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT access token.

    Returns the raw payload dict on success.

    Raises:
        jose.JWTError — if the signature is invalid, the token is expired,
                        or the token is malformed.

    Callers (deps.py) are responsible for catching JWTError and converting
    it to an HTTP 401.  This function deliberately has no HTTP knowledge.
    """
    settings = get_settings()

    # jose.jwt.decode validates signature + expiry automatically.
    # options={"verify_exp": True} is the default; listed explicitly for clarity.
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": True},
    )


# ── Public re-export for type checking ───────────────────────────────────────

# deps.py catches this specific exception type, so expose it from here
# to avoid a direct dependency on jose across multiple files.
TokenDecodeError = JWTError
