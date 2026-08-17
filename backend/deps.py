"""Shared FastAPI dependencies: current user resolution and role gates."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import Role, User
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    try:
        payload = decode_access_token(token)
    except Exception as exc:  # jwt.PyJWTError and friends
        raise _CREDENTIALS_ERROR from exc

    email = payload.get("sub")
    if not email:
        raise _CREDENTIALS_ERROR

    user = db.query(User).filter(User.email == email).first()
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user


def require_roles(*roles: Role):
    """Dependency factory restricting an endpoint to the given roles."""

    allowed = set(roles)

    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(r.value for r in allowed)}",
            )
        return user

    return _guard


# Convenience gates
require_manager = require_roles(Role.admin, Role.manager)
require_staff = require_roles(Role.admin, Role.manager, Role.staff)
