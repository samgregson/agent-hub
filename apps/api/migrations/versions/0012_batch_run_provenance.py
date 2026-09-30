"""Persist Batch Run initiator provenance.

Revision ID: 0012_batch_run_provenance
Revises: 0011_batch_run_definition_lifecycle
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0012_batch_run_provenance"
down_revision = "0011_batch_run_definition_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("batch_runs", sa.Column("initiator_subject", sa.String(length=320)))


def downgrade() -> None:
    op.drop_column("batch_runs", "initiator_subject")
