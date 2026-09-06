"""SQLite storage for the 共影 (watch-together) video records."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import aiosqlite

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "cove.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    title TEXT,
    source_type TEXT NOT NULL,
    source_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    duration REAL,
    transcript_path TEXT,
    error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(SCHEMA)
        await db.commit()


async def create_video_record(
    video_id: str, title: str, source_type: str, source_url: Optional[str]
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO videos (video_id, title, source_type, source_url, status)
               VALUES (?, ?, ?, ?, 'pending')""",
            (video_id, title, source_type, source_url),
        )
        await db.commit()


async def update_video(video_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = "__NOW__"
    set_clauses = []
    values: list[Any] = []
    for key, value in fields.items():
        if value == "__NOW__":
            set_clauses.append(f"{key} = datetime('now')")
            continue
        if key == "metadata_json" and isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        set_clauses.append(f"{key} = ?")
        values.append(value)
    values.append(video_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE videos SET {', '.join(set_clauses)} WHERE video_id = ?", values
        )
        await db.commit()


async def get_video(video_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM videos WHERE video_id = ?", (video_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_videos() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM videos ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_video(video_id: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
        await db.commit()
