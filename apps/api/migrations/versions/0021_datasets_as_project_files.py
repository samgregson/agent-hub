"""Move Dataset content into registered Project Files.

Revision ID: 0021_datasets_as_project_files
Revises: 0020_batch_run_initiation
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0021_datasets_as_project_files"
down_revision = "0020_batch_run_initiation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    datasets = connection.execute(
        sa.text("SELECT * FROM datasets ORDER BY project_id, dataset_id")
    ).mappings()
    for dataset in datasets:
        records = connection.execute(
            sa.text(
                """SELECT record_id, position, source_key, value FROM dataset_records
                WHERE project_id=:project_id AND dataset_id=:dataset_id ORDER BY position"""
            ),
            {"project_id": dataset["project_id"], "dataset_id": dataset["dataset_id"]},
        ).mappings()
        document = {
            "kind": "dataset",
            "schemaVersion": 1,
            "id": dataset["dataset_id"],
            "name": dataset["name"],
            "records": [
                {
                    "id": record["record_id"],
                    "position": record["position"],
                    "sourceKey": record["source_key"],
                    "value": record["value"],
                }
                for record in records
            ],
        }
        connection.execute(
            sa.text(
                """INSERT INTO project_files
                (project_id, path, content, version, created_at, updated_at)
                VALUES (:project_id, :path, :content, 1, :created_at, :updated_at)"""
            ),
            {
                "project_id": dataset["project_id"],
                "path": f"/.datasets/{dataset['dataset_id']}.json",
                "content": json.dumps(document, allow_nan=False),
                "created_at": dataset["created_at"],
                "updated_at": dataset["updated_at"],
            },
        )
    # Keep the existing rows as a query/rollback projection. The Project File
    # is canonical after this migration; application writes update both in
    # one transaction, and readers reconstruct Datasets from the file.


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """DELETE FROM project_files AS file USING datasets AS dataset
            WHERE file.project_id=dataset.project_id
            AND file.path='/.datasets/' || dataset.dataset_id || '.json'"""
        )
    )
