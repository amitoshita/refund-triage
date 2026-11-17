"""Append-only reviewer decision log (SQLite). Nothing is updated or deleted."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
create table if not exists decisions (
    id integer primary key autoincrement,
    request_id text not null,
    action text not null,          -- approve_full | approve_partial | reject | request_info | escalate
    amount_usd real,               -- refund amount actually granted (approve / partial)
    detail text,                   -- reject reason / info requested / escalated to
    note text,                     -- reviewer's justification
    reviewer text not null,
    lane text,
    suggested text,                -- the system's suggested action, for override tracking
    rule_version integer,
    decided_at text not null
)
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


def record(con: sqlite3.Connection, **row) -> None:
    row.setdefault("decided_at", datetime.now(UTC).strftime("%Y-%m-%d %H:%M"))
    cols = ", ".join(row)
    con.execute(f"insert into decisions ({cols}) values ({', '.join('?' * len(row))})", list(row.values()))
    con.commit()


def all_decisions(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("select * from decisions order by id desc")]


def latest_by_request(con: sqlite3.Connection) -> dict[str, dict]:
    out = {}
    for r in con.execute("select * from decisions order by id"):
        out[r["request_id"]] = dict(r)
    return out
