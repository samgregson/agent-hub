"""Delete Batch Runs when their Batch Definition is deleted.

Revision ID: 0011_batch_run_definition_lifecycle
Revises: 0010_batch_run_idempotency
"""

from collections.abc import Sequence

from alembic import op

revision = "0011_batch_run_definition_lifecycle"
down_revision = "0010_batch_run_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """ALTER TABLE batch_runs ADD CONSTRAINT fk_batch_runs_definition
        FOREIGN KEY (project_id, batch_definition_id)
        REFERENCES batch_definitions (project_id, batch_definition_id)
        ON DELETE CASCADE NOT VALID"""
    )


def downgrade() -> None:
    op.drop_constraint("fk_batch_runs_definition", "batch_runs", type_="foreignkey")
