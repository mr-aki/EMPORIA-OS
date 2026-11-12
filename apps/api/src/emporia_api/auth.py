from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import secrets
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session

from emporia_api.config import settings
from emporia_api.database import get_session
from emporia_api.models import User, WorkspaceMembership


_password_hash = PasswordHash.recommended()


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    role: str
    auth_type: str


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except Exception:
        return False


def _jwt_signing_key() -> str:
    if settings.jwt_secret is not None:
        key = settings.jwt_secret.get_secret_value()
        if len(key) >= 32:
            return key
    if settings.environment in {"development", "test"}:
        return "emporia-local-development-key-not-for-production-2026"
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Configure EMPORIA_JWT_SECRET with at least 32 characters",
    )


def create_access_token(user_id: str, workspace_id: str) -> str:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.jwt_access_token_minutes)
    claims = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": expires,
        "type": "access",
    }
    return jwt.encode(claims, _jwt_signing_key(), algorithm="HS256")


def get_current_principal(
    authorization: Annotated[str | None, Header()] = None,
    session: Session = Depends(get_session),
) -> Principal:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Bearer access token is required")

    # Temporary, local-only compatibility for the initial self-hosted development mode.
    if (
        settings.environment == "development"
        and secrets.compare_digest(token, settings.api_token)
    ):
        return Principal(
            user_id="local-development",
            workspace_id=settings.workspace_id,
            role="owner",
            auth_type="development",
        )

    try:
        claims = jwt.decode(
            token,
            _jwt_signing_key(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "workspace_id", "iat", "exp", "iss"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token") from exc

    user_id = claims.get("sub")
    workspace_id = claims.get("workspace_id")
    if not isinstance(user_id, str) or not isinstance(workspace_id, str):
        raise HTTPException(status_code=401, detail="Invalid access token claims")
    if claims.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid access token type")

    user = session.scalar(
        select(User).where(User.id == user_id, User.is_active.is_(True))
    )
    if user is None:
        raise HTTPException(status_code=401, detail="User is inactive or no longer exists")

    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Workspace membership is not active")

    return Principal(
        user_id=user.id,
        workspace_id=workspace_id,
        role=membership.role,
        auth_type="jwt",
    )


def require_write_access(principal: Principal) -> None:
    if principal.role not in {"owner", "admin", "operator"}:
        raise HTTPException(status_code=403, detail="Workspace role does not allow this action")
