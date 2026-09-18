"""Persist reviewed Plugin selections for each Project.

Revision ID: 0005_plugin_selections
Revises: 0004_project_files
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_plugin_selections"
down_revision: str | None = "0004_project_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_plugin_selections",
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("plugin_id", sa.String(length=120), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("project_plugin_selections")
