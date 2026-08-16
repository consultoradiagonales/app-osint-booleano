from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .boolean_parser import ast_dict, discovery_queries, parse
from .pipeline import load_json, run_pipeline
from .storage import RunStore


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rastreador OSINT-BOOLEANO deterministico (sin IA ni APIs pagas)")
    parser.add_argument("query", help='Consulta: ejemplo: UCR AND (convencion OR autoridades) NOT nacional')
    parser.add_argument("--config", default=str(PACKAGE_ROOT / "config" / "sources.json"))
    parser.add_argument("--aliases", default=str(PACKAGE_ROOT / "config" / "aliases.json"))
    parser.add_argument("--database", default=str(PACKAGE_ROOT / "data" / "bridge.sqlite3"))
    parser.add_argument("--since-days", type=int, default=7)
    parser.add_argument("--max-results", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true", help="Valida y muestra pivotes sin acceder a internet")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_json(args.config)
        aliases = load_json(args.aliases) if Path(args.aliases).exists() else {}
        root = parse(args.query)
        if args.dry_run:
            payload = {
                "query": args.query,
                "ast": ast_dict(root),
                "discovery_queries": discovery_queries(
                    args.query, root, aliases, int(config.get("max_discovery_queries", 12))
                ),
                "ai_used": False,
            }
        else:
            store = RunStore(args.database)
            payload = run_pipeline(
                args.query,
                config,
                aliases,
                max(1, args.since_days),
                max(1, args.max_results),
                store,
            ).to_dict()
        print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "ai_used": False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
