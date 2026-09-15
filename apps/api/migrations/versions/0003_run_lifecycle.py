"""Add durable Run lifecycle coordination.

Revision ID: 0003_run_lifecycle
Revises: 0002_threads_and_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_run_lifecycle"
down_revision: str | None = "0002_threads_and_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("request_id", sa.String(length=128), nullable=True))
    op.execute("UPDATE agent_runs SET request_id = id WHERE request_id IS NULL")
    op.alter_column("agent_runs", "request_id", nullable=False)

    # A process may have stopped before recording its terminal state. Clear
    # those legacy rows before adding the cross-process active-Run guard.
    op.execute(
        """
        UPDATE agent_runs
        SET status = CASE
                WHEN status = 'cancelling' THEN 'cancelled'
                ELSE 'failed'
            END,
            updated_at = CURRENT_TIMESTAMP
        WHERE status IN ('queued', 'running', 'cancelling')
        """
    )
    op.create_index(
        "uq_agent_runs_thread_active",
        "agent_runs",
        ["thread_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'cancelling')"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_runs_thread_active", table_name="agent_runs")
    op.drop_column("agent_runs", "request_id")
