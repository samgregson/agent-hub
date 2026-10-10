"""Join Project File Binding and Artifact audit migration histories.

Revision ID: 0025_merge_binding_and_artifact_heads
Revises: 0024_file_binding_version, 0022_artifact_audit_events
"""

from collections.abc import Sequence

revision = "0025_merge_binding_and_artifact_heads"
down_revision = ("0024_file_binding_version", "0022_artifact_audit_events")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
