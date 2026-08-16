"""Ejecutor programado del rastreo para la instalación Windows."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    app_root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    sys.path.insert(0, str(app_root))
    from bridge.watcher import main as watcher_main

    return watcher_main([
        "--sources", str(app_root / "config" / "sources.json"),
        "--aliases", str(app_root / "config" / "aliases.json"),
        "--database", str(app_root / "data" / "bridge.sqlite3"),
        "--watches", str(app_root / "config" / "watch_queries.json"),
        "--alerts-dir", str(app_root / "alerts"),
        "--reports-dir", str(app_root / "reports"),
    ])


if __name__ == "__main__":
    raise SystemExit(main())
