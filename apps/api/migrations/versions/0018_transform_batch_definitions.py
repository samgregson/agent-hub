"""Allow saved Batch Definitions to target Project Transform Definitions.

Revision ID: 0018_transform_batch_definitions
Revises: 0017_transform_runtime_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0018_transform_batch_definitions"
down_revision = "0017_transform_runtime_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("batch_definitions", "plugin_id", nullable=True)
    op.alter_column("batch_definitions", "tool_name", nullable=True)
    op.add_column(
        "batch_definitions",
        sa.Column("transform_definition_id", sa.String(length=36), nullable=True),
    )
    op.create_check_constraint(
        "batch_definition_target_exclusive",
        "batch_definitions",
        "(transform_definition_id IS NOT NULL AND plugin_id IS NULL AND tool_name IS NULL) "
        "OR (transform_definition_id IS NULL AND plugin_id IS NOT NULL AND tool_name IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("batch_definition_target_exclusive", "batch_definitions")
    op.drop_column("batch_definitions", "transform_definition_id")
    op.alter_column("batch_definitions", "tool_name", nullable=False)
    op.alter_column("batch_definitions", "plugin_id", nullable=False)
