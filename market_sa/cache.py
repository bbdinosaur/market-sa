"""On-disk JSON cache (SQLite) so repeat evaluations are instant and APIs are not hammered."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from market_sa.config import HTTP_CACHE_PATH, ensure_dirs

_LOCK = threading.Lock()
_INITED = False


def _connect(path: Path | None = None) -> sqlite3.Connection:
    ensure_dirs()
    p = path or HTTP_CACHE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kv (
            namespace TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (namespace, key)
        )
        """
    )
    return conn


def cache_get(namespace: str, key: str, *, path: Path | None = None) -> Any | None:
    with _LOCK:
        conn = _connect(path)
        try:
            row = conn.execute(
                "SELECT value FROM kv WHERE namespace = ? AND key = ?",
                (namespace, key),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row[0])
        finally:
            conn.close()


def cache_set(namespace: str, key: str, value: Any, *, path: Path | None = None) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    with _LOCK:
        conn = _connect(path)
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO kv (namespace, key, value, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (namespace, key, payload, time.time()),
            )
            conn.commit()
        finally:
            conn.close()
