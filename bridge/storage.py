from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from .models import RunResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  query TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC);
"""


class RunStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def save(self, result: RunResult) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    "INSERT OR REPLACE INTO runs(run_id, created_at, query, payload_json) VALUES (?, ?, ?, ?)",
                    (result.run_id, result.completed_at, result.query, json.dumps(result.to_dict(), ensure_ascii=False)),
                )

    def get(self, run_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT payload_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def latest(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT run_id, created_at, query, payload_json FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def latest_high_alerts(self, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        alerts: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for run in self.latest(100):
            for item in run.get("results", []):
                if item.get("confidence") != "alta":
                    continue
                url = str(item.get("url", "")).strip()
                key = url.casefold().rstrip("/")
                if not url or key in seen_urls:
                    continue
                seen_urls.add(key)
                alerts.append({
                    "title": item.get("title", "Sin título"),
                    "subtitle": item.get("subtitle", ""),
                    "summary": item.get("summary", ""),
                    "ai_summary": item.get("ai_summary", ""),
                    "political_analysis": item.get("political_analysis", ""),
                    "desk": item.get("desk", ""),
                    "alternate_urls": item.get("alternate_urls", []),
                    "url": url,
                    "source": item.get("source", "Fuente pública"),
                    "mentions": int(item.get("mentions", 1) or 1),
                    "confidence": "alta",
                    "relevance_score": int(item.get("relevance_score", 0) or 0),
                    "published_at": item.get("published_at"),
                    "run_id": run.get("run_id"),
                    "created_at": run.get("completed_at") or run.get("created_at"),
                    "watch_id": run.get("watch_id", ""),
                    "watch_label": run.get("watch_label", ""),
                })
                if len(alerts) >= limit:
                    return alerts
        return alerts

    def recent_high_alerts(self, hours: int = 3, limit: int = 200) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, int(hours)))
        alerts: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for run in self.latest(200):
            created = run.get("completed_at") or run.get("created_at") or ""
            try:
                if datetime.fromisoformat(created.replace("Z", "+00:00")) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            for item in run.get("results", []):
                if item.get("confidence") != "alta":
                    continue
                url = str(item.get("url", "")).strip()
                key = url.casefold().rstrip("/")
                if not url or key in seen_urls:
                    continue
                seen_urls.add(key)
                alerts.append({
                    "title": item.get("title", "Sin título"), "subtitle": item.get("subtitle", ""),
                    "summary": item.get("summary", ""), "ai_summary": item.get("ai_summary", ""),
                    "political_analysis": item.get("political_analysis", ""), "url": url,
                    "desk": item.get("desk", ""),
                    "alternate_urls": item.get("alternate_urls", []),
                    "source": item.get("source", "Fuente pública"),
                    "mentions": int(item.get("mentions", 1) or 1), "confidence": "alta",
                    "relevance_score": int(item.get("relevance_score", 0) or 0),
                    "published_at": item.get("published_at"), "run_id": run.get("run_id"), "created_at": created,
                    "watch_id": run.get("watch_id", ""), "watch_label": run.get("watch_label", ""),
                })
                if len(alerts) >= max(1, min(int(limit), 500)):
                    return alerts
        return alerts
