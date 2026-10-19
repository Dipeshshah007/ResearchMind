"""SQLite persistence (zero-setup, free). Stores the paper library and edit history."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings

DB_PATH = settings.data_dir / "researchmind.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, authors TEXT DEFAULT '', year INTEGER,
  venue TEXT DEFAULT '', venue_type TEXT DEFAULT 'Other',
  abstract TEXT DEFAULT '', url TEXT DEFAULT '', source TEXT DEFAULT 'upload',
  content TEXT DEFAULT '', notes TEXT DEFAULT '',
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS paper_versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id INTEGER NOT NULL,
  content TEXT, label TEXT, saved_at TEXT
);
"""

EDITABLE = {"title", "authors", "year", "venue", "venue_type", "abstract", "url", "notes", "content"}
LIST_COLS = "id,title,authors,year,venue,venue_type,abstract,url,source,notes,created_at,updated_at,length(content) AS content_len"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


def add_paper(d: dict) -> int:
    now = _now()
    with conn() as c:
        cur = c.execute(
            "INSERT INTO papers(title,authors,year,venue,venue_type,abstract,url,source,content,notes,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (d.get("title") or "Untitled", d.get("authors", ""), d.get("year"), d.get("venue", ""),
             d.get("venue_type", "Other"), d.get("abstract", ""), d.get("url", ""), d.get("source", "upload"),
             d.get("content", ""), d.get("notes", ""), now, now),
        )
        return cur.lastrowid


def list_papers(year=None, venue_type=None, q=None, source=None) -> list[dict]:
    where, args = [], []
    if year:
        where.append("year=?"); args.append(year)
    if venue_type:
        where.append("venue_type=?"); args.append(venue_type)
    if source:
        where.append("source=?"); args.append(source)
    if q:
        where.append("(title LIKE ? OR authors LIKE ? OR venue LIKE ?)"); args += [f"%{q}%"] * 3
    sql = f"SELECT {LIST_COLS} FROM papers" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated_at DESC"
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args)]


def get_paper(pid: int):
    with conn() as c:
        r = c.execute("SELECT * FROM papers WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None


def update_paper(pid: int, fields: dict):
    cur = get_paper(pid)
    if not cur:
        return None
    fields = {k: v for k, v in fields.items() if k in EDITABLE and v is not None}
    if not fields:
        return cur
    with conn() as c:
        if "content" in fields and fields["content"] != cur["content"]:
            c.execute("INSERT INTO paper_versions(paper_id,content,label,saved_at) VALUES(?,?,?,?)",
                      (pid, cur["content"], "Before edit", _now()))
        sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=?"
        c.execute(f"UPDATE papers SET {sets} WHERE id=?", [*fields.values(), _now(), pid])
    return get_paper(pid)


def delete_paper(pid: int) -> bool:
    with conn() as c:
        c.execute("DELETE FROM paper_versions WHERE paper_id=?", (pid,))
        return c.execute("DELETE FROM papers WHERE id=?", (pid,)).rowcount > 0


def list_versions(pid: int) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id,label,saved_at,content FROM paper_versions WHERE paper_id=? ORDER BY id DESC LIMIT 30", (pid,))]
