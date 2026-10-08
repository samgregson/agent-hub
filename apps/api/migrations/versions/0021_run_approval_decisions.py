"""Retain resolved approval decisions with their resume Runs.

Revision ID: 0021_run_approval_decisions
Revises: 0020_batch_run_initiation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_run_approval_decisions"
down_revision: str | None = "0020_batch_run_initiation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("approval_decisions", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "approval_decisions")
