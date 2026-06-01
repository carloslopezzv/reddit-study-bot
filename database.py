"""
database.py — Capa SQLite del bot.

Responsabilidades:
- Evitar reprocesar posts/comments ya vistos (cache de dedup).
- Anti-spam: recordar autores ya respondidos por el dueño.
- Stats diarias (posts evaluados, scoreados alto, enviados, costo Haiku).
- Tracking de alertas ya enviadas (para no repetir la misma alerta).

El archivo .db se cachea entre corridas de GitHub Actions, así el estado
persiste. Todas las operaciones son idempotentes y seguras ante concurrencia
baja (un solo proceso a la vez).
"""

import sqlite3
import datetime
from contextlib import contextmanager

import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS posts_processed (
    post_id     TEXT PRIMARY KEY,
    subreddit   TEXT,
    score       INTEGER,           -- score de Haiku (NULL si fue prefiltrado)
    sent        INTEGER DEFAULT 0, -- 1 si se mandó a Telegram
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS comments_processed (
    comment_id  TEXT PRIMARY KEY,
    post_id     TEXT,
    score       INTEGER,
    sent        INTEGER DEFAULT 0,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS replied_authors (
    author      TEXT PRIMARY KEY,
    replied_at  TEXT
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date              TEXT PRIMARY KEY,
    posts_evaluated   INTEGER DEFAULT 0,  -- pasaron pre-filtro y fueron a Haiku
    scored_high       INTEGER DEFAULT 0,  -- score >= umbral
    sent_to_telegram  INTEGER DEFAULT 0,
    haiku_cost        REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS sent_alerts (
    alert_key   TEXT PRIMARY KEY,
    sent_at     TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT
);
"""


def _today() -> str:
    return datetime.date.today().isoformat()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Database:
    def __init__(self, path: str = None):
        self.path = path or config.DB_PATH
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # -- context manager ----------------------------------------------------
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass

    # -- dedup de posts -----------------------------------------------------
    def is_post_seen(self, post_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM posts_processed WHERE post_id = ?", (post_id,)
        )
        return cur.fetchone() is not None

    def mark_post(self, post_id, subreddit, score=None, sent=False):
        self.conn.execute(
            """INSERT OR REPLACE INTO posts_processed
               (post_id, subreddit, score, sent, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (post_id, subreddit, score, 1 if sent else 0, _now()),
        )
        self.conn.commit()

    # -- dedup de comments --------------------------------------------------
    def is_comment_seen(self, comment_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM comments_processed WHERE comment_id = ?", (comment_id,)
        )
        return cur.fetchone() is not None

    def mark_comment(self, comment_id, post_id, score=None, sent=False):
        self.conn.execute(
            """INSERT OR REPLACE INTO comments_processed
               (comment_id, post_id, score, sent, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (comment_id, post_id, score, 1 if sent else 0, _now()),
        )
        self.conn.commit()

    # -- anti-spam de autores ----------------------------------------------
    def is_author_replied(self, author: str) -> bool:
        if not author:
            return False
        cur = self.conn.execute(
            "SELECT 1 FROM replied_authors WHERE author = ?", (author.lower(),)
        )
        return cur.fetchone() is not None

    def mark_author_replied(self, author: str):
        if not author:
            return
        self.conn.execute(
            "INSERT OR REPLACE INTO replied_authors (author, replied_at) VALUES (?, ?)",
            (author.lower(), _now()),
        )
        self.conn.commit()

    # -- stats diarias ------------------------------------------------------
    def _ensure_today_row(self):
        self.conn.execute(
            "INSERT OR IGNORE INTO daily_stats (date) VALUES (?)", (_today(),)
        )

    def bump_stat(self, field: str, amount=1):
        """Incrementa un contador de daily_stats para hoy.

        field ∈ {posts_evaluated, scored_high, sent_to_telegram, haiku_cost}
        """
        allowed = {"posts_evaluated", "scored_high", "sent_to_telegram", "haiku_cost"}
        if field not in allowed:
            raise ValueError(f"campo de stat inválido: {field}")
        self._ensure_today_row()
        self.conn.execute(
            f"UPDATE daily_stats SET {field} = {field} + ? WHERE date = ?",
            (amount, _today()),
        )
        self.conn.commit()

    def get_today_cost(self) -> float:
        cur = self.conn.execute(
            "SELECT haiku_cost FROM daily_stats WHERE date = ?", (_today(),)
        )
        row = cur.fetchone()
        return float(row["haiku_cost"]) if row else 0.0

    def get_today_stats(self) -> dict:
        self._ensure_today_row()
        cur = self.conn.execute(
            "SELECT * FROM daily_stats WHERE date = ?", (_today(),)
        )
        row = cur.fetchone()
        return dict(row) if row else {}

    def get_cumulative_cost(self) -> float:
        cur = self.conn.execute("SELECT SUM(haiku_cost) AS total FROM daily_stats")
        row = cur.fetchone()
        return float(row["total"]) if row and row["total"] is not None else 0.0

    # -- alertas (idempotencia) --------------------------------------------
    def was_alert_sent(self, alert_key: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM sent_alerts WHERE alert_key = ?", (alert_key,)
        )
        return cur.fetchone() is not None

    def mark_alert_sent(self, alert_key: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO sent_alerts (alert_key, sent_at) VALUES (?, ?)",
            (alert_key, _now()),
        )
        self.conn.commit()
