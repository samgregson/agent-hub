"""Retain how a Batch Run was initiated.

Revision ID: 0020_batch_run_initiation
Revises: 0019_transform_run_execution_context
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0020_batch_run_initiation"
down_revision = "0019_transform_run_execution_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "batch_runs",
        sa.Column(
            "initiation",
            sa.JSON(),
            nullable=False,
            server_default=sa.text('\'{"kind":"legacy","approval":"unknown"}\'::json'),
        ),
    )
    op.alter_column("batch_runs", "initiation", server_default=None)


def downgrade() -> None:
    op.drop_column("batch_runs", "initiation")
