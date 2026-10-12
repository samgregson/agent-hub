"""Replace Transform Definitions and Runs with reusable Functions.

Revision ID: 0029_functions_replace_transform_runs
Revises: 0028_remove_legacy_batch_storage
"""

from collections.abc import Sequence

from alembic import op

revision = "0029_functions_replace_transform_runs"
down_revision = "0028_remove_legacy_batch_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_transform_runs_definition_created", table_name="transform_runs")
    op.drop_table("transform_runs")
    op.drop_column("transform_definitions", "input_selectors")
    op.rename_table("transform_definitions", "functions")
    op.execute(
        "ALTER TABLE functions RENAME CONSTRAINT transform_definitions_pkey TO functions_pkey"
    )
    op.alter_column(
        "functions",
        "transform_definition_id",
        new_column_name="function_id",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Transform Runs and selection rules are not restored; restore from a database snapshot."
    )
