"""Add shared, pseudonymous failed-login rate limit counters."""

from alembic import op
import sqlalchemy as sa


revision = "0008_login_rate_limits"
down_revision = "0007_background_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_attempt_rate_limits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subject_type",
            "subject_hash",
            name="uq_login_attempt_rate_limit_subject",
        ),
    )
    op.create_index(
        "ix_login_attempt_rate_limits_window_start",
        "login_attempt_rate_limits",
        ["window_start"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_login_attempt_rate_limits_window_start",
        table_name="login_attempt_rate_limits",
    )
    op.drop_table("login_attempt_rate_limits")
