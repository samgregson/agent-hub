"""Keep payload-free Artifact mutations as append-only audit records.

Revision ID: 0022_artifact_audit_events
Revises: 0021_run_approval_decisions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_artifact_audit_events"
down_revision: str | None = "0021_run_approval_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("actor_kind", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.String(length=240), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_artifact_audit_events_project_artifact",
        "artifact_audit_events",
        ["project_id", "artifact_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_artifact_audit_events_project_artifact", table_name="artifact_audit_events")
    op.drop_table("artifact_audit_events")
