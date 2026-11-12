import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from emporia_api.config import settings


def require_api_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    expected = f"Bearer {settings.api_token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if settings.api_token == "change-me-before-deploy" and settings.environment != "development":
        raise HTTPException(status_code=503, detail="Configure EMPORIA_API_TOKEN before deployment")
    return "api-token"
