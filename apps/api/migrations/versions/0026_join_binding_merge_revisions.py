"""Join both published Binding/Artifact migration merge revisions.

Revision ID: 0026_join_binding_merge_revisions
Revises: 0025_merge_binding_and_artifact_heads, 0025_merge_foundation_and_bindings
"""

from collections.abc import Sequence

revision = "0026_join_binding_merge_revisions"
down_revision = (
    "0025_merge_binding_and_artifact_heads",
    "0025_merge_foundation_and_bindings",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
