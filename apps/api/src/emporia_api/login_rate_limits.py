"""Database-backed login throttling with HMAC-pseudonymized subjects."""

import hmac
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import ceil
from uuid import uuid4

from sqlalchemy import case, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from emporia_api.models import LoginAttemptRateLimit


class LoginRateLimitExceeded(Exception):
    """Raised when an email or client IP exhausts its login-failure allowance."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__("Login attempt rate limit reached")


def login_subject_digest(subject_type: str, value: str, secret: str) -> str:
    """Return a keyed digest so raw emails and IP addresses are never persisted."""
    message = f"emporia-login:{subject_type}:{value}".encode()
    return hmac.new(secret.encode(), message, sha256).hexdigest()


def _bucket_start(now: datetime, window_seconds: int) -> datetime:
    timestamp = int(now.timestamp())
    start = timestamp - timestamp % window_seconds
    return datetime.fromtimestamp(start, tz=UTC)


def _as_utc(value: datetime) -> datetime:
    # SQLite may return timezone-aware columns as naive datetimes.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _retry_after(now: datetime, bucket_start: datetime, window_seconds: int) -> int:
    next_window = bucket_start + timedelta(seconds=window_seconds)
    return max(1, ceil((next_window - now).total_seconds()))


def enforce_login_attempt_limits(
    session: Session,
    subjects: tuple[tuple[str, str, int], ...],
    window_seconds: int,
    *,
    now: datetime | None = None,
) -> None:
    """Reject requests whose email or client-IP counter is already at its limit."""
    current_time = now or datetime.now(UTC)
    bucket = _bucket_start(current_time, window_seconds)
    for subject_type, subject_hash, limit in subjects:
        row = session.scalar(
            select(LoginAttemptRateLimit).where(
                LoginAttemptRateLimit.subject_type == subject_type,
                LoginAttemptRateLimit.subject_hash == subject_hash,
            )
        )
        if (
            row is not None
            and _as_utc(row.window_start) == bucket
            and row.attempt_count >= limit
        ):
            raise LoginRateLimitExceeded(_retry_after(current_time, bucket, window_seconds))


def record_failed_login_attempts(
    session: Session,
    subjects: tuple[tuple[str, str, int], ...],
    window_seconds: int,
    *,
    now: datetime | None = None,
) -> None:
    """Atomically charge email and IP counters in one SQLite/PostgreSQL transaction."""
    current_time = now or datetime.now(UTC)
    bucket = _bucket_start(current_time, window_seconds)
    table = LoginAttemptRateLimit.__table__

    # Keep only the current and previous two windows for inactive subjects.
    session.execute(
        delete(LoginAttemptRateLimit).where(
            LoginAttemptRateLimit.window_start < bucket - timedelta(seconds=window_seconds * 2)
        )
    )

    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        insert_statement = sqlite_insert(table)
    elif dialect == "postgresql":
        insert_statement = postgresql_insert(table)
    else:
        raise RuntimeError(
            f"Login rate limiting is unsupported for database dialect: {dialect}"
        )

    for subject_type, subject_hash, limit in subjects:
        values = {
            "id": str(uuid4()),
            "subject_type": subject_type,
            "subject_hash": subject_hash,
            "window_start": bucket,
            "attempt_count": 1,
            "updated_at": current_time,
        }
        statement = insert_statement.values(**values).on_conflict_do_update(
            index_elements=[table.c.subject_type, table.c.subject_hash],
            set_={
                "window_start": case(
                    (table.c.window_start != bucket, bucket),
                    else_=table.c.window_start,
                ),
                "attempt_count": case(
                    (table.c.window_start != bucket, 1),
                    else_=table.c.attempt_count + 1,
                ),
                "updated_at": current_time,
            },
            where=or_(
                table.c.window_start != bucket,
                table.c.attempt_count < limit,
            ),
        ).returning(table.c.attempt_count)

        count = session.execute(statement).scalar_one_or_none()
        if count is None:
            raise LoginRateLimitExceeded(_retry_after(current_time, bucket, window_seconds))


def clear_login_attempts(session: Session, subject_type: str, subject_hash: str) -> None:
    """Clear a successfully authenticated email counter; retain the shared IP budget."""
    session.execute(
        delete(LoginAttemptRateLimit).where(
            LoginAttemptRateLimit.subject_type == subject_type,
            LoginAttemptRateLimit.subject_hash == subject_hash,
        )
    )
