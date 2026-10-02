"""Seed or verify application and LangGraph state around a PostgreSQL restore."""

import asyncio
import sys

from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection

from agent_hub_api.settings import Settings

_THREAD_ID = "foundation-restore-drill"
_MARKER = "checkpoint survives restore"


async def run(mode: str) -> None:
    settings = Settings()
    database_url = str(settings.database_url)
    connection = await AsyncConnection.connect(database_url)
    async with connection:
        cursor = await connection.execute("SELECT count(*) FROM projects")
        row = await cursor.fetchone()
        assert row is not None and row[0] > 0, "No application Projects to restore"

    async with AsyncPostgresSaver.from_conn_string(database_url) as saver:
        if mode == "seed":
            await saver.setup()
            checkpoint = empty_checkpoint()
            checkpoint["channel_values"] = {"restore_marker": _MARKER}
            await saver.aput(
                {"configurable": {"thread_id": _THREAD_ID, "checkpoint_ns": ""}},
                checkpoint,
                {"source": "input", "step": 0, "parents": {}},
                {},
            )
        saved = await saver.aget_tuple(
            {"configurable": {"thread_id": _THREAD_ID, "checkpoint_ns": ""}}
        )
        assert saved is not None, "LangGraph checkpoint was not restored"
        assert saved.checkpoint["channel_values"]["restore_marker"] == _MARKER


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"seed", "verify"}:
        raise SystemExit("usage: foundation-restore-drill.py seed|verify")
    asyncio.run(run(sys.argv[1]))
