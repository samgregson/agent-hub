"""Keep captured Result Records in Dataset selection order.

Revision ID: 0014_order_batch_result_records
Revises: 0013_archive_batch_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0014_order_batch_result_records"
down_revision = "0013_archive_batch_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("batch_result_records", sa.Column("position", sa.Integer(), nullable=True))
    op.execute("UPDATE batch_result_records SET position=0 WHERE position IS NULL")
    op.alter_column("batch_result_records", "position", nullable=False)


def downgrade() -> None:
    op.drop_column("batch_result_records", "position")
