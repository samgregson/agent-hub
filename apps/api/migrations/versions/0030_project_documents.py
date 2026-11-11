"""Retain original documents alongside protected searchable Project Files."""

import sqlalchemy as sa
from alembic import op

revision = "0030_project_documents"
down_revision = "0029_functions_replace_transform_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_documents",
        sa.Column(
            "project_id",
            sa.Text(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("document_id", sa.Text(), primary_key=True),
        sa.Column("source", sa.LargeBinary(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Document originals are not discarded automatically; restore a database backup."
    )
