"""Store Project-owned Transform Definitions.

Revision ID: 0015_transform_definitions
Revises: 0014_order_batch_result_records
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0015_transform_definitions"
down_revision = "0014_order_batch_result_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transform_definitions",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("transform_definition_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("input_selectors", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("runtime", sa.String(length=80), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "transform_definition_id"),
    )


def downgrade() -> None:
    op.drop_table("transform_definitions")
