"""
CV storage in a single SQLite file (data/cvs.db). No database server needed.

Each row keeps the current CV (edited by staff) and the original data exactly as
the website sent it, so nothing is lost if the conversion needs fixing later.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid

from config import DATA_DIR

DB_PATH = DATA_DIR / "cvs.db"
STATUSES = ("new", "in_review", "ready")
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


_conn = _connect()
with _lock:
    _conn.executescript("""
    CREATE TABLE IF NOT EXISTS cvs (
        id          TEXT PRIMARY KEY,
        external_id TEXT,
        source      TEXT NOT NULL DEFAULT 'manual',
        status      TEXT NOT NULL DEFAULT 'new',
        name        TEXT NOT NULL DEFAULT '',
        email       TEXT NOT NULL DEFAULT '',
        data        TEXT NOT NULL,
        original    TEXT,
        warnings    TEXT NOT NULL DEFAULT '[]',
        created_at  REAL NOT NULL,
        updated_at  REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_cvs_external ON cvs(external_id);
    CREATE INDEX IF NOT EXISTS idx_cvs_updated ON cvs(updated_at);
    """)
    _conn.commit()


def _summary_fields(cv: dict) -> tuple[str, str]:
    p = cv.get("personal") or {}
    name = f"{p.get('first_name') or ''} {p.get('last_name') or ''}".strip()
    return name, (p.get("email") or "")


def _row(r: sqlite3.Row | None, full: bool = True) -> dict | None:
    if r is None:
        return None
    out = {
        "id": r["id"], "external_id": r["external_id"], "source": r["source"],
        "status": r["status"], "name": r["name"], "email": r["email"],
        "warnings": json.loads(r["warnings"] or "[]"),
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }
    if full:
        out["cv"] = json.loads(r["data"])
        out["original"] = json.loads(r["original"]) if r["original"] else None
    return out


def create(cv: dict, *, source: str = "manual", external_id: str | None = None,
           original: dict | None = None, warnings: list[str] | None = None, status: str = "new") -> dict:
    cv_id = uuid.uuid4().hex[:12]
    now = time.time()
    name, email = _summary_fields(cv)
    with _lock:
        _conn.execute(
            "INSERT INTO cvs (id, external_id, source, status, name, email, data, original, warnings, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cv_id, external_id, source, status, name, email, json.dumps(cv, ensure_ascii=False),
             json.dumps(original, ensure_ascii=False) if original is not None else None,
             json.dumps(warnings or []), now, now))
        _conn.commit()
    return get(cv_id)


def get(cv_id: str) -> dict | None:
    with _lock:
        r = _conn.execute("SELECT * FROM cvs WHERE id = ?", (cv_id,)).fetchone()
    return _row(r)


def find_external(external_id: str) -> dict | None:
    with _lock:
        r = _conn.execute("SELECT * FROM cvs WHERE external_id = ? ORDER BY created_at DESC LIMIT 1",
                          (external_id,)).fetchone()
    return _row(r)


def update(cv_id: str, *, cv: dict | None = None, status: str | None = None,
           original: dict | None = None, warnings: list[str] | None = None) -> dict | None:
    sets, args = ["updated_at = ?"], [time.time()]
    if cv is not None:
        name, email = _summary_fields(cv)
        sets += ["data = ?", "name = ?", "email = ?"]
        args += [json.dumps(cv, ensure_ascii=False), name, email]
    if status is not None:
        if status not in STATUSES:
            raise ValueError(f"Status must be one of: {', '.join(STATUSES)}.")
        sets.append("status = ?")
        args.append(status)
    if original is not None:
        sets.append("original = ?")
        args.append(json.dumps(original, ensure_ascii=False))
    if warnings is not None:
        sets.append("warnings = ?")
        args.append(json.dumps(warnings))
    with _lock:
        cur = _conn.execute(f"UPDATE cvs SET {', '.join(sets)} WHERE id = ?", (*args, cv_id))
        _conn.commit()
    return get(cv_id) if cur.rowcount else None


def delete(cv_id: str) -> bool:
    with _lock:
        cur = _conn.execute("DELETE FROM cvs WHERE id = ?", (cv_id,))
        _conn.commit()
    return cur.rowcount > 0


def list_cvs(query: str = "", status: str = "", limit: int = 200, offset: int = 0) -> tuple[list[dict], int]:
    where, args = [], []
    if query:
        where.append("(name LIKE ? OR email LIKE ? OR external_id LIKE ?)")
        like = f"%{query}%"
        args += [like, like, like]
    if status:
        where.append("status = ?")
        args.append(status)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    with _lock:
        total = _conn.execute(f"SELECT COUNT(*) FROM cvs {clause}", args).fetchone()[0]
        rows = _conn.execute(f"SELECT * FROM cvs {clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                             (*args, limit, offset)).fetchall()
    return [_row(r, full=False) for r in rows], total


def counts() -> dict:
    with _lock:
        rows = _conn.execute("SELECT status, COUNT(*) FROM cvs GROUP BY status").fetchall()
    out = {s: 0 for s in STATUSES}
    out.update({r[0]: r[1] for r in rows})
    return out
