"""Remove Batch Definitions and Batch Runs superseded by Workflows.

Revision ID: 0028_remove_legacy_batch_storage
Revises: 0027_function_input_schema
"""

from collections.abc import Sequence

from alembic import op

revision = "0028_remove_legacy_batch_storage"
down_revision = "0027_function_input_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("batch_result_records")
    op.drop_table("batch_runs")
    op.drop_table("batch_definitions")


def downgrade() -> None:
    raise RuntimeError("Legacy Batch storage is not restored; restore from a database snapshot.")
