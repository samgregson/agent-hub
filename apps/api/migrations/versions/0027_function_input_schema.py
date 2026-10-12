"""Declare Python Function input contracts.

Revision ID: 0027_function_input_schema
Revises: 0026_workflow_run_execution
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0027_function_input_schema"
down_revision = "0026_workflow_run_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transform_definitions",
        sa.Column(
            "input_schema",
            sa.JSON(),
            nullable=False,
            server_default=sa.text('\'{"type":"object"}\''),
        ),
    )


def downgrade() -> None:
    op.drop_column("transform_definitions", "input_schema")
