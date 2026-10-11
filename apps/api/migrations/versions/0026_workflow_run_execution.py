"""Store Workflow Run node outcomes.

Revision ID: 0026_workflow_run_execution
Revises: 0025_workflow_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0026_workflow_run_execution"
down_revision = "0025_workflow_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("execution", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "execution")
