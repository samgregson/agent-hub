"""Declare the MCP argument supplied by a Project File Binding.

Revision ID: 0022_file_binding_argument
Revises: 0021_datasets_as_project_files
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0022_file_binding_argument"
down_revision = "0021_datasets_as_project_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("batch_definitions", sa.Column("file_argument", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("batch_definitions", "file_argument")
