from __future__ import annotations

import argparse
from contextlib import closing
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .pipeline import canonical_url, item_allowed_by_policy, load_json, run_pipeline
from .recipients import RecipientStore
from .reports import write_high_alert_report
from .storage import RunStore


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


SEEN_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_alerts (
  watch_id TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  title TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  PRIMARY KEY (watch_id, canonical_url)
);
"""


class SeenStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.executescript(SEEN_SCHEMA)

    def unseen(self, watch_id: str, items: list[Any]) -> list[Any]:
        with closing(sqlite3.connect(self.path)) as connection:
            known = {
                row[0]
                for row in connection.execute(
                    "SELECT canonical_url FROM seen_alerts WHERE watch_id = ?", (watch_id,)
                )
            }
        return [item for item in items if canonical_url(item.url) not in known]

    def mark(self, watch_id: str, items: list[Any]) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        rows = [(watch_id, canonical_url(item.url), item.title, stamp) for item in items]
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                connection.executemany(
                    "INSERT OR IGNORE INTO seen_alerts(watch_id, canonical_url, title, first_seen_at) VALUES (?, ?, ?, ?)",
                    rows,
                )


ALERT_LEVELS = ("alta", "media", "baja")


def alert_title(level: str, label: str = "") -> str:
    from datetime import datetime
    normalized = str(level).strip().lower()
    if normalized not in ALERT_LEVELS:
        normalized = "baja"
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    return f"CABLE DE NOTICIAS · {date_str}"


def build_alert_text(label: str, items: list[Any], total: int, limit: int, level: str = "alta") -> str:
    from datetime import datetime
    normalized = str(level).strip().lower()
    if normalized not in ALERT_LEVELS:
        normalized = "baja"
    limit = max(1, min(int(limit), 20))
    date_str = datetime.now().strftime("%d de %B de %Y, %H:%M hs")
    lines = [
        f"CABLE DE NOTICIAS · {date_str}",
        f"{total} artículo(s) detectado(s).",
        "",
    ]
    for index, item in enumerate(items[:limit], 1):
        subtitle = (getattr(item, "subtitle", "") or "").strip()
        summary = (getattr(item, "summary", "") or "").strip()
        political_analysis = (getattr(item, "political_analysis", "") or "").strip()
        alternate_urls = list(getattr(item, "alternate_urls", []) or [])
        if not subtitle:
            subtitle = summary.split(".", 1)[0][:240] if summary else f"Fuente: {item.source}"
        if not summary:
            summary = f"Fuente: {item.source}."
        lines.extend(
            [
                f"{index}. {item.title}",
                f"{subtitle}",
                f"Fuente: {item.source} · {item.mentions} menciones",
                f"{item.url}",
                *([f"Análisis político: {political_analysis}"] if political_analysis else []),
                *(["Otras fuentes:", *alternate_urls] if alternate_urls else []),
                "",
            ]
        )
    if total > limit:
        lines.append(f"+ {total - limit} artículo(s) adicional(es).")
    return "\n".join(lines).strip()


def _execute_watchers_unlocked(
    source_config_path: str,
    aliases_path: str,
    watches_path: str,
    database_path: str,
    alerts_dir: str,
    reports_dir: str | None = None,
    scheduled: bool = False,
) -> dict[str, Any]:
    source_config = load_json(source_config_path)
    aliases = load_json(aliases_path)
    watch_config = load_json(watches_path)
    run_store = RunStore(database_path)
    seen_store = SeenStore(database_path)
    summaries: list[dict[str, Any]] = []
    digest_items: list[Any] = []
    digest_watch_ids: list[str] = []

    for watch in watch_config.get("watches", []):
        if not watch.get("enabled", True):
            continue
        if scheduled:
            now = datetime.now()
            if now.hour not in {int(hour) for hour in watch.get("schedule_hours", [7, 15, 20])}:
                continue
            # Lunes=0, domingo=6. Los monitores anteriores conservan lunes a viernes.
            if now.weekday() not in {int(day) for day in watch.get("schedule_days", [0, 1, 2, 3, 4])}:
                continue
        result = run_pipeline(
            watch["query"],
            source_config,
            aliases,
            int(watch.get("since_days", 3)),
            int(watch.get("max_results", 100)),
            run_store,
            watch_id=watch["id"],
            watch_label=watch["label"],
        )
        minimum = int(watch.get("minimum_relevance", 60))
        qualifying = [item for item in result.results if item.relevance_score >= minimum]
        new_items = seen_store.unseen(watch["id"], qualifying)
        items_by_level = {
            level: [item for item in new_items if item.confidence == level]
            for level in ALERT_LEVELS
        }
        notifications: list[dict[str, object]] = []
        # One consolidated cable per execution prevents separate notifications
        # for every confidence level and every monitor.
        digest_items.extend(new_items)
        if new_items:
            digest_watch_ids.append(str(watch["id"]))
        if new_items:
            seen_store.mark(watch["id"], new_items)
        summaries.append(
            {
                "watch_id": watch["id"],
                "label": watch["label"],
                "run_id": result.run_id,
                "matched": result.total_matched,
                "qualifying": len(qualifying),
                "new_items": len(new_items),
                "new_high_alerts": len(items_by_level["alta"]),
                "new_medium_alerts": len(items_by_level["media"]),
                "new_low_alerts": len(items_by_level["baja"]),
                "notification": None,
                "notifications": notifications,
                "source_errors": result.errors,
            }
        )
    digest_notification: dict[str, object] | None = None
    if digest_items:
        deduplicated: list[Any] = []
        seen_urls: set[str] = set()
        for item in sorted(digest_items, key=lambda value: (value.relevance_score, value.official, value.published_at or ""), reverse=True):
            key = canonical_url(item.url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            deduplicated.append(item)
        title = alert_title("alta", "Resumen editorial")
        body = build_alert_text("Resumen editorial consolidado", deduplicated, len(deduplicated), int(watch_config.get("max_alert_items", 20)), "alta")
        digest_notification = {
            "delivery": "rss",
            "title": title,
            "items": len(deduplicated),
            "watch_ids": digest_watch_ids,
            "body": body,
        }

    recent_alerts = [
        item
        for item in run_store.recent_high_alerts(24, 200)
        if item_allowed_by_policy(item, source_config)
    ]
    report = write_high_alert_report(
        reports_dir or str(PACKAGE_ROOT / "reports"),
        recent_alerts,
        PACKAGE_ROOT / "config" / "AGENCIA_DE_NOTICIAS.md",
    )
    return {
        "ok": True,
        "name": "Rastreador OSINT-BOOLEANO",
        "watchers": summaries,
        "digest_notification": digest_notification,
        "high_alerts": [
            item
            for item in run_store.latest_high_alerts(100)
            if item_allowed_by_policy(item, source_config)
        ][:20],
        "report": report,
        "ai_used": False,
        "paid_services_used": False,
    }


def execute_watchers(
    source_config_path: str,
    aliases_path: str,
    watches_path: str,
    database_path: str,
    alerts_dir: str,
    reports_dir: str | None = None,
    scheduled: bool = False,
) -> dict[str, Any]:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\ConsultoraDiagonalesOSINTBooleano")
    acquired = kernel32.WaitForSingleObject(handle, 0) in {0, 0x80}
    if not acquired:
        kernel32.CloseHandle(handle)
        return {
            "ok": True,
            "name": "Rastreador OSINT-BOOLEANO",
            "watchers": [],
            "skipped": "Ya existe un rastreo en ejecución",
            "ai_used": False,
            "paid_services_used": False,
        }
    try:
        return _execute_watchers_unlocked(
            source_config_path, aliases_path, watches_path, database_path,
            alerts_dir, reports_dir, scheduled,
        )
    finally:
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ejecuta los monitores OSINT-BOOLEANOS configurados")
    parser.add_argument("--sources", default=str(PACKAGE_ROOT / "config" / "sources.json"))
    parser.add_argument("--aliases", default=str(PACKAGE_ROOT / "config" / "aliases.json"))
    parser.add_argument("--watches", default=str(PACKAGE_ROOT / "config" / "watch_queries.json"))
    parser.add_argument("--database", default=str(PACKAGE_ROOT / "data" / "bridge.sqlite3"))
    parser.add_argument("--alerts-dir", default=str(PACKAGE_ROOT / "alerts"))
    parser.add_argument("--reports-dir", default=str(PACKAGE_ROOT / "reports"))
    parser.add_argument("--scheduled", action="store_true", help="Ejecuta únicamente los monitores asignados a la hora actual")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = execute_watchers(args.sources, args.aliases, args.watches, args.database, args.alerts_dir, args.reports_dir, args.scheduled)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "ai_used": False, "paid_services_used": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
