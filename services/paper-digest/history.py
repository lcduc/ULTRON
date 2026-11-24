"""SQLite history: every paper seen, feedback, concepts taught, Drive folders, reports, link queue."""

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import engine

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
  id TEXT PRIMARY KEY, digest_date TEXT, number INTEGER, level TEXT, total REAL,
  title TEXT, one_liner TEXT, data TEXT, added TEXT);
CREATE INDEX IF NOT EXISTS papers_date ON papers(digest_date, number);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, paper_id TEXT, level TEXT, source TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS concepts (
  concept TEXT PRIMARY KEY, paper_id TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS drive (paper_id TEXT PRIMARY KEY, folder_id TEXT, url TEXT);
CREATE TABLE IF NOT EXISTS numbers (ym TEXT PRIMARY KEY, n INTEGER);
CREATE TABLE IF NOT EXISTS reports (paper_id TEXT PRIMARY KEY, markdown TEXT, chat_id TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, source TEXT, status TEXT DEFAULT 'new',
  note TEXT, added TEXT, finished TEXT);
"""

# keys that score()/select() add to a Paper
_SCORE_KEYS = ("scores", "track", "one_liner", "why", "total", "level", "number", "runner_up", "fallback")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _day(d) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


class _Closing:
    """sqlite3 connection as a context manager that commits and then really closes."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()
        return False


class History:
    """One short-lived connection per call plus a lock: safe for the scheduler and HTTP threads."""

    def __init__(self, path=None):
        self.path = str(path or engine.STATE_DIR / "history.db")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._conn() as c:
            c.executescript(_SCHEMA)
            cols = {r["name"] for r in c.execute("PRAGMA table_info(queue)")}
            if "tries" not in cols:  # added 2026-11-24: retries for temporary failures
                c.execute("ALTER TABLE queue ADD COLUMN tries INTEGER DEFAULT 0")
            if "not_before" not in cols:
                c.execute("ALTER TABLE queue ADD COLUMN not_before TEXT")

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        return _Closing(c)

    # ---- papers
    def seen(self, paper_id: str) -> bool:
        with self._lock, self._conn() as c:
            return c.execute("SELECT 1 FROM papers WHERE id=?", (paper_id,)).fetchone() is not None

    def add(self, scored: dict, digest_date) -> None:
        """Store (or replace) a scored paper. digest_date: date or 'YYYY-MM-DD'."""
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO papers(id, digest_date, number, level, total, title, one_liner, data, added)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (scored["id"], _day(digest_date), scored.get("number"), scored.get("level"), scored.get("total"),
                 scored.get("title"), scored.get("one_liner"), json.dumps(scored, ensure_ascii=False), _now()))

    def get(self, paper_id: str) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT data, digest_date FROM papers WHERE id=?", (paper_id,)).fetchone()
        if not row:
            return None
        out = json.loads(row["data"])
        out.setdefault("digest_date", row["digest_date"])
        return out

    def digest_paper(self, digest_date, number: int) -> str | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT id FROM papers WHERE digest_date=? AND number=? ORDER BY added DESC",
                            (_day(digest_date), int(number))).fetchone()
        return row["id"] if row else None

    def runners_up(self, days: int = 7) -> list[dict]:
        """Papers that lost only on budget in the last `days` days, as plain Papers (scores removed),
        best total first. They stay in the table; a later add() replaces the row."""
        since = (date.today() - timedelta(days=days)).isoformat()
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT data FROM papers WHERE level='runner_up' AND digest_date>=?"
                             " ORDER BY total DESC", (since,)).fetchall()
        out = []
        for r in rows:
            p = json.loads(r["data"])
            for k in _SCORE_KEYS:
                p.pop(k, None)
            out.append(p)
        return out

    # ---- feedback
    def feedback_add(self, paper_id: str, level: str, source: str = "reply") -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO feedback(paper_id, level, source, at) VALUES (?,?,?,?)",
                      (paper_id, level, source, _now()))

    def feedback_examples(self, n: int = 10) -> list[dict]:
        """Latest feedback per paper, newest first: [{title, one_liner, level}] (level = what the user wanted)."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT p.title, p.one_liner, f.level FROM feedback f JOIN papers p ON p.id=f.paper_id"
                " WHERE f.id IN (SELECT MAX(id) FROM feedback GROUP BY paper_id)"
                " ORDER BY f.id DESC LIMIT ?", (int(n),)).fetchall()
        return [{"title": r["title"], "one_liner": r["one_liner"] or "", "level": r["level"]} for r in rows]

    # ---- concepts taught
    def concepts(self) -> list[str]:
        with self._lock, self._conn() as c:
            return [r["concept"] for r in c.execute("SELECT concept FROM concepts ORDER BY at, concept")]

    def concepts_add(self, items: list[str], paper_id: str) -> None:
        with self._lock, self._conn() as c:
            for it in items:
                it = (it or "").strip()
                if it:
                    c.execute("INSERT OR IGNORE INTO concepts(concept, paper_id, at) VALUES (?,?,?)",
                              (it, paper_id, _now()))

    # ---- Drive
    def drive_folder(self, paper_id: str) -> str | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT folder_id FROM drive WHERE paper_id=?", (paper_id,)).fetchone()
        return row["folder_id"] if row else None

    def set_drive_folder(self, paper_id: str, folder_id: str, url: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO drive(paper_id, folder_id, url) VALUES (?,?,?)",
                      (paper_id, folder_id, url))

    def next_paper_number(self, year: int, month: int) -> int:
        """Reserve and return the next running number for that month (1, 2, 3, ...)."""
        ym = f"{int(year):04d}-{int(month):02d}"
        with self._lock, self._conn() as c:
            row = c.execute("SELECT n FROM numbers WHERE ym=?", (ym,)).fetchone()
            n = (row["n"] if row else 0) + 1
            c.execute("INSERT OR REPLACE INTO numbers(ym, n) VALUES (?,?)", (ym, n))
        return n

    # ---- reports
    def set_report(self, paper_id: str, markdown: str, chat_id: str | None) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO reports(paper_id, markdown, chat_id, at) VALUES (?,?,?,?)",
                      (paper_id, markdown, chat_id, _now()))

    def report(self, paper_id: str) -> dict | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT markdown, chat_id FROM reports WHERE paper_id=?", (paper_id,)).fetchone()
        return {"markdown": row["markdown"], "chat_id": row["chat_id"]} if row else None

    def paper_for_chat(self, chat_id: str) -> str | None:
        """Paper id whose Deep-read chat this is, or None."""
        with self._lock, self._conn() as c:
            row = c.execute("SELECT paper_id FROM reports WHERE chat_id=? ORDER BY at DESC LIMIT 1",
                            (chat_id,)).fetchone()
        return row["paper_id"] if row else None

    # ---- link queue
    def queue_add(self, url: str, source: str = "chat") -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("INSERT INTO queue(url, source, added) VALUES (?,?,?)", (url.strip(), source, _now()))
            return cur.lastrowid

    def queue_next(self) -> dict | None:
        """Oldest waiting item as {id, url, source}; it is marked 'running'."""
        with self._lock, self._conn() as c:
            row = c.execute("SELECT id, url, source, COALESCE(tries, 0) AS tries FROM queue WHERE status='new' "
                            "AND (not_before IS NULL OR not_before <= ?) ORDER BY id LIMIT 1", (_now(),)).fetchone()
            if not row:
                return None
            c.execute("UPDATE queue SET status='running' WHERE id=?", (row["id"],))
        return dict(row)

    def queue_reset_running(self) -> int:
        """At startup: items left 'running' by a restart go back to the queue. Returns how many."""
        with self._lock, self._conn() as c:
            return c.execute("UPDATE queue SET status='new' WHERE status='running'").rowcount

    def queue_retry(self, qid: int, note: str, minutes: float) -> int:
        """Puts a running item back in the queue, not before `minutes` from now; returns its try count."""
        later = (datetime.now() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
        with self._lock, self._conn() as c:
            c.execute("UPDATE queue SET status='new', note=?, tries=COALESCE(tries, 0)+1, not_before=? WHERE id=?",
                      (note, later, qid))
            row = c.execute("SELECT tries FROM queue WHERE id=?", (qid,)).fetchone()
        return int(row["tries"]) if row else 0

    def queue_done(self, qid: int, ok: bool, note: str = "") -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE queue SET status=?, note=?, finished=? WHERE id=?",
                      ("done" if ok else "failed", note, _now(), qid))
