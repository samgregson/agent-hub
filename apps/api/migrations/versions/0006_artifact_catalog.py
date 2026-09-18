"""Add the indexed projection for Project-owned Artifact documents.

Revision ID: 0006_artifact_catalog
Revises: 0005_plugin_selections
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_artifact_catalog"
down_revision: str | None = "0005_plugin_selections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_catalog",
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("artifact_id", sa.String(length=128), primary_key=True),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=240), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("plugin_id", sa.String(length=120), nullable=False),
        sa.Column("plugin_version", sa.String(length=120), nullable=False),
        sa.Column("schema_id", sa.String(length=240), nullable=False),
        sa.Column("schema_version", sa.String(length=120), nullable=False),
        sa.Column("created_by_thread_id", sa.String(length=128), nullable=False),
        sa.Column("created_by_run_id", sa.String(length=128), nullable=False),
        sa.Column("last_changed_by_thread_id", sa.String(length=128), nullable=False),
        sa.Column("last_changed_by_run_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "path"],
            ["project_files.project_id", "project_files.path"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("project_id", "path"),
    )


def downgrade() -> None:
    op.drop_table("artifact_catalog")
