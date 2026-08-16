from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
from email.utils import parseaddr
from pathlib import Path
import re
import sqlite3
from typing import Any


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_recipients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS delivery_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recipient_email TEXT NOT NULL,
  watch_id TEXT NOT NULL,
  subject TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_delivery_log_created_at ON delivery_log(created_at DESC);
"""


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    _, parsed = parseaddr(email)
    if parsed != email or len(email) > 254 or not EMAIL_RE.fullmatch(email):
        raise ValueError("Dirección de correo inválida")
    return email


class RecipientStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.executescript(SCHEMA)

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "email": row["email"],
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = " WHERE enabled = 1" if enabled_only else ""
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"SELECT * FROM alert_recipients{where} ORDER BY name COLLATE NOCASE, email COLLATE NOCASE"
            ).fetchall()
        return [self._row(row) for row in rows]

    def add(self, email: str, name: str = "") -> dict[str, Any]:
        normalized = normalize_email(email)
        stamp = datetime.now(timezone.utc).isoformat()
        try:
            with closing(sqlite3.connect(self.path)) as connection:
                with connection:
                    cursor = connection.execute(
                        "INSERT INTO alert_recipients(email, name, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
                        (normalized, name.strip()[:120], stamp, stamp),
                    )
                    recipient_id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("Ese correo ya está registrado") from exc
        return self.get(int(recipient_id))

    def get(self, recipient_id: int) -> dict[str, Any]:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                "SELECT * FROM alert_recipients WHERE id = ?", (recipient_id,)
            ).fetchone()
        if not row:
            raise KeyError("Destinatario no encontrado")
        return self._row(row)

    def update(self, recipient_id: int, *, name: str | None = None, enabled: bool | None = None) -> dict[str, Any]:
        current = self.get(recipient_id)
        stamp = datetime.now(timezone.utc).isoformat()
        next_name = current["name"] if name is None else str(name).strip()[:120]
        next_enabled = current["enabled"] if enabled is None else bool(enabled)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute(
                    "UPDATE alert_recipients SET name = ?, enabled = ?, updated_at = ? WHERE id = ?",
                    (next_name, int(next_enabled), stamp, recipient_id),
                )
        return self.get(recipient_id)

    def delete(self, recipient_id: int) -> None:
        self.get(recipient_id)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute("DELETE FROM alert_recipients WHERE id = ?", (recipient_id,))

    def log_delivery(
        self,
        recipient_email: str,
        watch_id: str,
        subject: str,
        status: str,
        error: str = "",
    ) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.execute(
                    "INSERT INTO delivery_log(recipient_email, watch_id, subject, status, error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (recipient_email.strip().lower(), watch_id[:120], subject[:300], status[:40], error[:1000], stamp),
                )

    def deliveries(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 500))
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM delivery_log ORDER BY created_at DESC, id DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return [dict(row) for row in rows]
