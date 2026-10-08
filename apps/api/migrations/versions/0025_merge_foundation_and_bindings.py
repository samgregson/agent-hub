"""Join foundation audit and Project File Binding migration histories.

Revision ID: 0025_merge_foundation_and_bindings
Revises: 0022_artifact_audit_events, 0024_file_binding_version
"""

from collections.abc import Sequence

revision = "0025_merge_foundation_and_bindings"
down_revision = ("0022_artifact_audit_events", "0024_file_binding_version")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
