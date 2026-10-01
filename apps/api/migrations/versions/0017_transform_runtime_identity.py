"""Capture Transform package lock identity.

Revision ID: 0017_transform_runtime_identity
Revises: 0016_transform_runs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0017_transform_runtime_identity"
down_revision = "0016_transform_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transform_definitions", sa.Column("package_hash", sa.String(64)))
    op.add_column("transform_runs", sa.Column("package_hash", sa.String(64)))


def downgrade() -> None:
    op.drop_column("transform_runs", "package_hash")
    op.drop_column("transform_definitions", "package_hash")
