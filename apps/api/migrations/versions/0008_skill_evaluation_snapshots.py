"""Persist immutable structural evaluation snapshots for skill runs."""

from alembic import op
import sqlalchemy as sa


revision = "0008_skill_evaluation_snapshots"
down_revision = "0007_background_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill_runs",
        sa.Column("evaluation_json", sa.Text(), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("skill_runs", "evaluation_json")
