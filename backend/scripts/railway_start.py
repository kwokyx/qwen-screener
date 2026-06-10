"""Railway container preflight before starting Uvicorn."""
from __future__ import annotations

import os
import sqlite3
import time


def _sqlite_path() -> str | None:
    url = os.getenv("DATABASE_URL", "")
    if url.startswith("sqlite:////"):
        return "/" + url[len("sqlite:////") :]
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///") :] or None
    return None


def _move_bad_wal(db_path: str) -> None:
    stamp = time.strftime("%Y%m%d%H%M%S")
    for suffix in ("-wal", "-shm"):
        path = f"{db_path}{suffix}"
        if os.path.exists(path):
            os.replace(path, f"{path}.bad-{stamp}")
            print(f"[RAILWAY_START] moved {path}", flush=True)


def _database_ok(db_path: str) -> bool:
    conn = sqlite3.connect(db_path)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    return bool(result and result[0] == "ok")


def main() -> int:
    db_path = _sqlite_path()
    if not db_path or not os.path.exists(db_path):
        return 0
    try:
        if _database_ok(db_path):
            return 0
    except sqlite3.DatabaseError:
        _move_bad_wal(db_path)
        try:
            if _database_ok(db_path):
                print("[RAILWAY_START] sqlite recovered after WAL cleanup", flush=True)
                return 0
        except sqlite3.DatabaseError:
            pass
        stamp = time.strftime("%Y%m%d%H%M%S")
        os.replace(db_path, f"{db_path}.bad-{stamp}")
        _move_bad_wal(db_path)
        print("[RAILWAY_START] moved malformed sqlite database aside", flush=True)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
