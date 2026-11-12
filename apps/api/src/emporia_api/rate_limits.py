from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import case, or_
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from emporia_api.models import WorkspaceExecutionRateLimit


class RateLimitExceeded(Exception):
    """Raised when a workspace exhausts its fixed-window execution allowance."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__("Workspace execution rate limit reached")


def consume_workspace_rate_limit(
    session: Session,
    workspace_id: str,
    execution_type: str,
    limit: int,
    *,
    now: datetime | None = None,
) -> int:
    """Atomically consume one workspace execution slot in the current UTC minute.

    The single-row-per-workspace/type upsert works across API workers on SQLite
    and PostgreSQL. The caller owns the transaction so the slot is committed
    atomically with the corresponding run and its audit event.
    """
    current_time = now or datetime.now(UTC)
    window_start = current_time.replace(second=0, microsecond=0)
    table = WorkspaceExecutionRateLimit.__table__
    values = {
        "id": str(uuid4()),
        "workspace_id": workspace_id,
        "execution_type": execution_type,
        "window_start": window_start,
        "request_count": 1,
        "updated_at": current_time,
    }

    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        insert_statement = sqlite_insert(table)
    elif dialect == "postgresql":
        insert_statement = postgresql_insert(table)
    else:
        raise RuntimeError(
            f"Workspace execution rate limiting is unsupported for database dialect: {dialect}"
        )

    statement = insert_statement.values(**values).on_conflict_do_update(
        index_elements=[table.c.workspace_id, table.c.execution_type],
        set_={
            "window_start": case(
                (table.c.window_start < window_start, window_start),
                else_=table.c.window_start,
            ),
            "request_count": case(
                (table.c.window_start < window_start, 1),
                else_=table.c.request_count + 1,
            ),
            "updated_at": current_time,
        },
        where=or_(
            table.c.window_start < window_start,
            table.c.request_count < limit,
        ),
    ).returning(table.c.request_count)

    request_count = session.execute(statement).scalar_one_or_none()
    if request_count is None:
        raise RateLimitExceeded(max(1, 60 - current_time.second))
    return request_count
