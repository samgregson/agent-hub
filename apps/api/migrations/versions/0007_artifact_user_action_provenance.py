"""Represent direct user Artifact actions without inventing an Agent Run.

Revision ID: 0007_artifact_user_action_provenance
Revises: 0006_artifact_catalog
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_artifact_user_action_provenance"
down_revision: str | None = "0006_artifact_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "artifact_catalog",
        sa.Column(
            "created_by_kind",
            sa.String(length=32),
            nullable=False,
            server_default="agentRun",
        ),
    )
    op.add_column(
        "artifact_catalog",
        sa.Column("created_by_user_action_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "artifact_catalog",
        sa.Column(
            "last_changed_by_kind",
            sa.String(length=32),
            nullable=False,
            server_default="agentRun",
        ),
    )
    op.add_column(
        "artifact_catalog",
        sa.Column("last_changed_by_user_action_id", sa.String(length=128), nullable=True),
    )
    op.alter_column("artifact_catalog", "created_by_thread_id", nullable=True)
    op.alter_column("artifact_catalog", "created_by_run_id", nullable=True)
    op.alter_column("artifact_catalog", "last_changed_by_thread_id", nullable=True)
    op.alter_column("artifact_catalog", "last_changed_by_run_id", nullable=True)
    op.execute(
        """
        UPDATE project_files AS files
        SET content = jsonb_set(
            files.content::jsonb,
            '{artifact,provenance}',
            jsonb_build_object(
                'createdBy', jsonb_build_object(
                    'kind', 'agentRun',
                    'threadId', catalog.created_by_thread_id,
                    'runId', catalog.created_by_run_id
                ),
                'lastChangedBy', jsonb_build_object(
                    'kind', 'agentRun',
                    'threadId', catalog.last_changed_by_thread_id,
                    'runId', catalog.last_changed_by_run_id
                )
            )
        )::text
        FROM artifact_catalog AS catalog
        WHERE files.project_id = catalog.project_id AND files.path = catalog.path
        """
    )
    op.alter_column("artifact_catalog", "created_by_kind", server_default=None)
    op.alter_column("artifact_catalog", "last_changed_by_kind", server_default=None)


def downgrade() -> None:
    raise RuntimeError(
        "Artifact UserAction provenance cannot be downgraded without losing direct-user audit data."
    )
