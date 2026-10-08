"""Protect concurrent edits to a file Binding.

Revision ID: 0024_file_binding_version
Revises: 0023_file_bindings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0024_file_binding_version"
down_revision = "0023_file_bindings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "file_bindings",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.alter_column("file_bindings", "version", server_default=None)


def downgrade() -> None:
    op.drop_column("file_bindings", "version")
