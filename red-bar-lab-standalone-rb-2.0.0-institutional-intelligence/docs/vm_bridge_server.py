"""rb-itos-ai sqlite read-only HTTP bridge.

Run on the VM:
    pip install fastapi 'uvicorn[standard]' pydantic
    python server.py

Then on this machine:
    gcloud compute ssh $VM -- -L 8765:127.0.0.1:8765 -N
    curl http://127.0.0.1:8765/healthz
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DB_PATH = os.environ.get(
    "RB_DB_PATH",
    "/home/aloknagaonkar46/RB-ITOS-AI/red-bar-lab-standalone-rb-2.0.0-institutional-intelligence/artifacts/red_bar/database/red_bar_strategy.db",
)
MAX_ROWS = int(os.environ.get("RB_MAX_ROWS", "5000"))

app = FastAPI(title="rb-itos-ai sqlite bridge", version="1.0.0")


class Query(BaseModel):
    sql: str = Field(..., min_length=1)
    params: list[Any] = Field(default_factory=list)


def _connect() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=500, detail=f"db not found: {DB_PATH}")
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "db_path": DB_PATH, "size_bytes": os.path.getsize(DB_PATH)}


@app.get("/schema")
def schema() -> dict:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall()
    return {"objects": [dict(r) for r in rows]}


@app.post("/query")
def query(q: Query) -> dict:
    head = q.sql.lstrip().split(None, 1)[0].lower() if q.sql.strip() else ""
    if head not in ("select", "with", "pragma"):
        raise HTTPException(
            status_code=400,
            detail="only SELECT/WITH/PRAGMA queries are allowed",
        )
    with _connect() as conn:
        cur = conn.execute(q.sql, q.params)
        cols = [c[0] for c in cur.description] if cur.description else []
        rows = [dict(r) for r in cur.fetchmany(MAX_ROWS)]
    return {"columns": cols, "row_count": len(rows), "rows": rows}
