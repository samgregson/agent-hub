"""Make Batch Run submission idempotent per Project.

Revision ID: 0010_batch_run_idempotency
Revises: 0009_batch_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0010_batch_run_idempotency"
down_revision = "0009_batch_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("batch_runs", sa.Column("idempotency_key", sa.String(length=128)))
    op.create_index(
        "uq_batch_runs_project_idempotency_key",
        "batch_runs",
        ["project_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_batch_runs_project_idempotency_key", table_name="batch_runs")
    op.drop_column("batch_runs", "idempotency_key")
