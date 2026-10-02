"""Retain Transform Run initiation and runner-limit context.

Revision ID: 0019_transform_run_execution_context
Revises: 0018_transform_batch_definitions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0019_transform_run_execution_context"
down_revision = "0018_transform_batch_definitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transform_runs",
        sa.Column(
            "initiation",
            sa.JSON(),
            nullable=False,
            server_default=sa.text('\'{"kind":"legacy","approval":"unknown"}\'::json'),
        ),
    )
    op.add_column(
        "transform_runs",
        sa.Column("limits", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.alter_column("transform_runs", "initiation", server_default=None)
    op.alter_column("transform_runs", "limits", server_default=None)


def downgrade() -> None:
    op.drop_column("transform_runs", "limits")
    op.drop_column("transform_runs", "initiation")
