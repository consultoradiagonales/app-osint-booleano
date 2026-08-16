from __future__ import annotations

import argparse
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta, timezone

from .boolean_parser import BooleanSyntaxError, parse
from .google_calendar import (
    google_calendar_status,
    publish_calendar_alert,
    remove_calendar_subscriber,
    sync_calendar_subscribers,
)
from .pipeline import item_allowed_by_policy, load_json, run_pipeline
from .recipients import RecipientStore
from .storage import RunStore
from .watcher import execute_watchers
from .windows_credentials import get_api_token


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
ALLOWED_TOPICS = {"Política", "Economía", "Educación", "Cultura", "Salud", "OTRO/S"}


class BridgeApp:
    def __init__(self, config_path: str, aliases_path: str, database_path: str, watches_path: str | None = None, alerts_dir: str | None = None, reports_dir: str | None = None):
        self.config = load_json(config_path)
        self.aliases = load_json(aliases_path) if Path(aliases_path).exists() else {}
        self.store = RunStore(database_path)
        self.recipients = RecipientStore(database_path)
        self.token = get_api_token()
        self.config_path = config_path
        self.aliases_path = aliases_path
        self.database_path = database_path
        self.watches_path = watches_path or str(PACKAGE_ROOT / "config" / "watch_queries.json")
        self.alerts_dir = alerts_dir or str(PACKAGE_ROOT / "alerts")
        self.reports_dir = reports_dir or str(PACKAGE_ROOT / "reports")
        self.watch_lock = threading.Lock()

    def _watch_config(self) -> dict[str, Any]:
        path = Path(self.watches_path)
        if not path.exists():
            return {"alert_mode": "outlook_or_ics", "max_alert_items": 5, "watches": []}
        payload = load_json(path)
        if not isinstance(payload.get("watches"), list):
            raise ValueError("La configuración de monitores no es válida")
        return payload

    def list_watches(self) -> dict[str, Any]:
        return {"ok": True, **self._watch_config(), "ai_used": False}

    def policy_alerts(self, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [item for item in alerts if item_allowed_by_policy(item, self.config)]

    def _validated_watch(self, payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        current = current or {}
        label = str(payload.get("label", current.get("label", ""))).strip()[:120]
        query = str(payload.get("query", current.get("query", ""))).strip()
        if not label:
            raise ValueError("El nombre del monitor es obligatorio")
        parse(query)
        identifier = str(payload.get("id", current.get("id", ""))).strip().casefold()
        if not identifier:
            identifier = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")[:64]
        if not identifier or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", identifier):
            raise ValueError("El identificador del monitor no es válido")
        enabled = payload.get("enabled", current.get("enabled", True))
        if not isinstance(enabled, bool):
            raise ValueError("'enabled' debe ser booleano")
        topics = payload.get("topics", current.get("topics") or ["Política"])
        if not isinstance(topics, list) or not topics or any(topic not in ALLOWED_TOPICS for topic in topics):
            raise ValueError("Elegí uno o más temas válidos")
        custom_terms = str(payload.get("custom_terms", current.get("custom_terms", ""))).strip()[:300]
        if "OTRO/S" in topics and not custom_terms:
            raise ValueError("Escribí el nombre, partido político o temática para OTRO/S")
        provinces = payload.get("provinces", current.get("provinces"))
        if provinces is None:
            legacy_province = str(payload.get("province", current.get("province", "Nacional"))).strip()
            provinces = [legacy_province or "Nacional"]
        if not isinstance(provinces, list) or not provinces:
            raise ValueError("Elegí una o más provincias")
        provinces = list(dict.fromkeys(str(province).strip()[:80] for province in provinces if str(province).strip()))
        if not provinces:
            raise ValueError("Elegí una o más provincias")
        if "Nacional" in provinces and len(provinces) > 1:
            provinces = ["Nacional"]
        schedule_hours = payload.get("schedule_hours", current.get("schedule_hours", [7, 15, 20]))
        if not isinstance(schedule_hours, list):
            raise ValueError("Los horarios no son válidos")
        schedule_hours = sorted(set(int(hour) for hour in schedule_hours))
        if not 1 <= len(schedule_hours) <= 3 or any(hour < 0 or hour > 23 for hour in schedule_hours):
            raise ValueError("El plan beta permite elegir entre uno y tres horarios")
        return {
            "id": identifier,
            "label": label,
            "enabled": enabled,
            "query": query,
            "since_days": max(1, min(int(payload.get("since_days", current.get("since_days", 3))), 3650)),
            "max_results": max(1, min(int(payload.get("max_results", current.get("max_results", 100))), 500)),
            "minimum_relevance": max(0, min(int(payload.get("minimum_relevance", current.get("minimum_relevance", 60))), 100)),
            "provinces": provinces,
            "city": str(payload.get("city", current.get("city", ""))).strip()[:120],
            "topics": topics,
            "custom_terms": custom_terms,
            "schedule_hours": schedule_hours,
        }

    def _save_watch_config(self, config: dict[str, Any]) -> None:
        path = Path(self.watches_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def add_watch(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.watch_lock:
            config = self._watch_config()
            watch = self._validated_watch(payload)
            if any(item.get("id") == watch["id"] for item in config["watches"]):
                raise ValueError("Ya existe un monitor con ese nombre")
            config["watches"].append(watch)
            self._save_watch_config(config)
        return watch

    def update_watch(self, watch_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.watch_lock:
            config = self._watch_config()
            index = next((index for index, item in enumerate(config["watches"]) if item.get("id") == watch_id), None)
            if index is None:
                raise KeyError("Monitor no encontrado")
            watch = self._validated_watch(payload, config["watches"][index])
            if watch["id"] != watch_id:
                raise ValueError("El identificador del monitor no puede modificarse")
            config["watches"][index] = watch
            self._save_watch_config(config)
        return watch

    def delete_watch(self, watch_id: str) -> None:
        with self.watch_lock:
            config = self._watch_config()
            retained = [item for item in config["watches"] if item.get("id") != watch_id]
            if len(retained) == len(config["watches"]):
                raise KeyError("Monitor no encontrado")
            config["watches"] = retained
            self._save_watch_config(config)

    def run_watchers(self) -> dict[str, Any]:
        if not self.watch_lock.acquire(blocking=False):
            raise RuntimeError("Ya hay un monitoreo en ejecución")
        try:
            return execute_watchers(
                self.config_path,
                self.aliases_path,
                self.watches_path,
                self.database_path,
                self.alerts_dir,
                self.reports_dir,
            )
        finally:
            self.watch_lock.release()

    def _topic_weights(self) -> dict[str, int]:
        """Returns topic → total historical mentions from historial_cables.json."""
        try:
            path = Path(self.reports_dir) / "historial_cables.json"
            if not path.is_file():
                return {}
            history = json.loads(path.read_text(encoding="utf-8"))
            from .reports import TOPIC_RULES
            counts: dict[str, int] = {}
            for entry in history:
                for item in entry.get("alerts", []):
                    text = " ".join([
                        str(item.get("title", "")),
                        str(item.get("subtitle", "")),
                        str(item.get("summary", "")),
                    ]).lower()
                    topic = "Actualidad general"
                    for name, kws in TOPIC_RULES.items():
                        if any(kw in text for kw in kws):
                            topic = name
                            break
                    counts[topic] = counts.get(topic, 0) + int(item.get("mentions", 1) or 1)
            return counts
        except Exception:
            return {}

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query", "")).strip()
        if not query:
            raise BooleanSyntaxError("El campo 'query' es obligatorio")
        since_days = max(1, min(int(payload.get("since_days", 7)), 3650))
        max_results = max(1, min(int(payload.get("max_results", 100)), 500))
        result = run_pipeline(
            query, self.config, self.aliases, since_days, max_results, self.store,
            watch_id="manual", watch_label="Búsqueda manual",
        )

        # ── 1. Query-term boost: items matching the user's specific terms get highest priority ──
        # Extract meaningful tokens from the query (quoted phrases + bare words ≥ 4 chars)
        _quoted = re.findall(r'"([^"]+)"', query)
        _bare = re.findall(r'\b([A-Za-záéíóúÁÉÍÓÚñÑüÜ]{4,})\b', query)
        query_terms = [t.lower() for t in _quoted + _bare
                       if t.lower() not in {"and", "not", "true", "false", "desde", "hasta", "que"}]

        for item in result.results:
            searchable = " ".join([item.title, item.subtitle, item.summary, item.source]).lower()
            matched = sum(1 for t in query_terms if t in searchable)
            # Up to +30 pts for direct query-term matches (capped per term to avoid runaway scores)
            query_boost = min(30, matched * 6)
            item.relevance_score = min(100, item.relevance_score + query_boost)

        # ── 2. Media-coverage boost: topics heavily covered in historical data float up ──
        topic_weights = self._topic_weights()
        if topic_weights:
            from .reports import TOPIC_RULES
            max_weight = max(topic_weights.values()) or 1
            for item in result.results:
                text = " ".join([item.title, item.subtitle, item.summary]).lower()
                topic = "Actualidad general"
                for name, kws in TOPIC_RULES.items():
                    if any(kw in text for kw in kws):
                        topic = name
                        break
                media_mentions = topic_weights.get(topic, 0)
                # Proportional boost: up to +20 points
                boost = round((media_mentions / max_weight) * 20)
                item.relevance_score = min(100, item.relevance_score + boost)

        # Re-sort: official first → boosted relevance desc → recency desc
        result.results.sort(
            key=lambda i: (i.official, i.relevance_score, i.published_at or ""),
            reverse=True,
        )

        # Send calendar alert for high-relevance results (≥70) to all enabled recipients
        # Manual searches are segmented with the explicit "Enviar búsqueda" action.
        # They must never broadcast to every active client automatically.
        return result.to_dict()
        high_items = [i for i in result.results if (i.relevance_score or 0) >= 70]
        if high_items:
            from .google_calendar import publish_calendar_alert
            from .watcher import alert_title, build_alert_text
            recipients = [r["email"] for r in self.recipients.list(enabled_only=True)]
            if recipients:
                label = f"Búsqueda manual · {query[:60]}"
                title = alert_title("alta", label)
                body = build_alert_text(label, high_items, len(high_items), 20, "alta")
                publish_calendar_alert(recipients, title, body, "alta")

        return result.to_dict()


    def _load_api_key(self) -> str:
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            for candidate in (
                PACKAGE_ROOT / ".env",
                PACKAGE_ROOT.parent / ".env",
                PACKAGE_ROOT.parent.parent / ".env",
            ):
                if candidate.is_file():
                    for line in candidate.read_text(encoding="utf-8").splitlines():
                        if line.startswith("ANTHROPIC_API_KEY="):
                            key = line.split("=", 1)[1].strip()
                            if key:
                                break
                if key:
                    break
        if not key:
            raise ValueError("No se encontró ANTHROPIC_API_KEY en las variables de entorno ni en ningún archivo .env")
        return key

    def analyze_with_haiku(self) -> dict[str, Any]:
        json_path = Path(self.reports_dir) / "ultimas_alertas_altas.json"
        if not json_path.exists():
            raise FileNotFoundError("No hay reporte de alertas generado aún. Ejecutá un rastreo primero.")
        report_data = json.loads(json_path.read_text(encoding="utf-8"))
        alerts = report_data.get("alerts", [])
        if not alerts:
            raise ValueError("El reporte no contiene alertas para analizar.")

        items_text = "\n".join(
            f"- {item.get('title', 'Sin título')} | Fuente: {item.get('source', '?')} | "
            f"Menciones: {item.get('mentions', 1)} | Relevancia: {item.get('relevance_score', 0)}/100"
            + (f"\n  Resumen: {item['summary']}" if item.get("summary") else "")
            for item in alerts[:15]
        )

        prompt = f"""Sos analista de la Mesa Editorial de Consultora Diagonales, especializada en inteligencia política y comunicación estratégica en Argentina.

Analizá las siguientes noticias detectadas por el Rastreador Booleano según los parámetros del proyecto Consultora Diagonales:

NOTICIAS DETECTADAS:
{items_text}

Respondé en español con este formato exacto:

## ANÁLISIS EDITORIAL — CONSULTORA DIAGONALES

**Tema dominante:** [el eje central de las noticias]
**Territorio:** [nacional / provincial / municipal]
**Actores clave:** [figuras o instituciones involucradas]

**Evaluación de relevancia política:**
[2-3 oraciones sobre la importancia estratégica del conjunto de noticias]

**Recomendación editorial:**
[¿Se justifica enviar el cable? ¿Qué noticias priorizar? ¿Alguna requiere verificación adicional?]

**Señales de alerta:** [cualquier aspecto sensible o que requiera cautela editorial]

No incluyas URLs ni datos de rastreo. El análisis es exclusivamente para uso interno de la Mesa Editorial."""

        api_key = self._load_api_key()
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                answer = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("error", {}).get("message", detail)
            except json.JSONDecodeError:
                pass
            raise RuntimeError(f"Anthropic API: {detail}") from exc
        text = "\n\n".join(
            block.get("text", "") for block in answer.get("content", []) if block.get("type") == "text"
        ).strip()
        if not text:
            raise RuntimeError("La API no devolvió contenido textual")
        return {
            "ok": True,
            "analysis": text,
            "alerts_analyzed": len(alerts[:15]),
            "model": answer.get("model", "claude-haiku-4-5-20251001"),
        }


def make_handler(app: BridgeApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RastreadorOSINTBooleano/1.3.8"

        def _json(self, status: int, payload: dict[str, Any] | list[Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", app.config.get("cors_origin", "http://127.0.0.1"))
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def _html(self, path: Path) -> None:
            if not path.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Panel no encontrado"})
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self' http: https:; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def _xml(self, path: Path) -> None:
            if not path.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "RSS no encontrado"})
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _xsl(self, path: Path) -> None:
            if not path.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Estilo RSS no encontrado"})
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/xsl; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _png(self, path: Path) -> None:
            if not path.is_file():
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Imagen no encontrada"})
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if self.client_address[0] in {"127.0.0.1", "::1"}:
                return True
            if not app.token:
                return False
            return self.headers.get("Authorization", "") == f"Bearer {app.token}"

        def do_OPTIONS(self) -> None:
            self._json(HTTPStatus.NO_CONTENT, {})

        def _payload(self) -> dict[str, Any]:
            length = min(max(int(self.headers.get("Content-Length", "0")), 0), 1_000_000)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("El cuerpo debe ser un objeto JSON")
            return payload

        def _recipient_id(self, path: str) -> int:
            return int(path.rstrip("/").rsplit("/", 1)[-1])

        def do_GET(self) -> None:
            path = urlparse(self.path)
            if path.path in {"/", "/mobile", "/mobile.html"}:
                self._html(PACKAGE_ROOT / "panel" / "mobile.html")
                return
            if path.path == "/assets/consultora_diagonales_logo.png":
                self._png(PACKAGE_ROOT / "panel" / "assets" / "consultora_diagonales_logo.png")
                return
            if path.path == "/reports/latest" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._html(Path(app.reports_dir) / "ultimas_alertas_altas.html")
                return
            if path.path == "/reports/mailing" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._html(Path(app.reports_dir) / "mailing.html")
                return
            if path.path == "/reports/rss.xml" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                # En navegador, la dirección histórica muestra el cable legible.
                self._html(Path(app.reports_dir) / "mailing.html")
                return
            if path.path == "/reports/feed.xml" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._html(Path(app.reports_dir) / "feed-politico.html")
                return
            if path.path == "/reports/agenda.xml" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._html(Path(app.reports_dir) / "feed-agenda.html")
                return
            if path.path == "/reports/boletin.xml" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._html(Path(app.reports_dir) / "feed-boletin.html")
                return
            if path.path == "/reports/geopolitica.xml" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._html(Path(app.reports_dir) / "feed-geopolitica.html")
                return
            if path.path == "/feeds/politico.rss" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._xml(Path(app.reports_dir) / "rss.xml")
                return
            if path.path == "/feeds/agenda.rss" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._xml(Path(app.reports_dir) / "agenda.xml")
                return
            if path.path == "/feeds/boletin.rss" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._xml(Path(app.reports_dir) / "boletin.xml")
                return
            if path.path == "/feeds/geopolitica.rss" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._xml(Path(app.reports_dir) / "geopolitica.xml")
                return
            if path.path == "/reports/rss.xsl" and (self.client_address[0] in {"127.0.0.1", "::1"} or self._authorized()):
                self._xsl(Path(app.reports_dir) / "rss.xsl")
                return
            if path.path == "/api/bridge/health":
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "name": "Rastreador OSINT-BOOLEANO",
                    "engine": "deterministic-local",
                    "ai_used": False,
                    "ai_enabled": bool(app.config.get("ai", {}).get("enabled", False)),
                    "ai_model": app.config.get("ai", {}).get("model", ""),
                    "paid_services_used": False,
                    "mobile_control": bool(app.token),
                })
                return
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "No autorizado"})
                return
            if path.path == "/api/bridge/runs":
                limit = min(int(parse_qs(path.query).get("limit", [20])[0]), 100)
                self._json(HTTPStatus.OK, app.store.latest(limit))
                return
            if path.path == "/api/bridge/alerts/high":
                params = parse_qs(path.query)
                hours = max(1, min(int(params.get("hours", [30])[0]), 48))
                limit = min(int(params.get("limit", [200])[0]), 500)
                alerts = app.policy_alerts(app.store.recent_high_alerts(hours, limit))
                self._json(HTTPStatus.OK, {"ok": True, "alerts": alerts})
                return
            if path.path == "/api/bridge/trends":
                params = parse_qs(path.query)
                hours = max(1, min(int(params.get("hours", [24])[0]), 72))
                limit = max(10, min(int(params.get("limit", [100])[0]), 200))
                alerts = app.policy_alerts(app.store.recent_high_alerts(hours, limit))
                self._json(HTTPStatus.OK, {"ok": True, "hours": hours, "alerts": alerts})
                return
            if path.path == "/api/bridge/reports":
                folder = Path(app.reports_dir)
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "folder": str(folder.resolve()),
                    "latest_url": "/reports/latest",
                    "latest_exists": (folder / "ultimas_alertas_altas.html").is_file(),
                })
                return
            if path.path == "/api/bridge/recipients":
                self._json(HTTPStatus.OK, {"ok": True, "recipients": app.recipients.list()})
                return
            if path.path == "/api/bridge/deliveries":
                limit = int(parse_qs(path.query).get("limit", [50])[0])
                self._json(HTTPStatus.OK, {"ok": True, "deliveries": app.recipients.deliveries(limit)})
                return
            if path.path == "/api/bridge/email/status":
                self._json(HTTPStatus.OK, {"ok": True, **google_calendar_status()})
                return
            if path.path == "/api/bridge/calendar/status":
                self._json(HTTPStatus.OK, {"ok": True, **google_calendar_status()})
                return
            if path.path == "/api/bridge/watch/status":
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "running": app.watch_lock.locked(),
                    "schedule_mode": "selectable_beta",
                    "allowed_hours": list(range(24)),
                    "max_schedule_hours": 3,
                    "recent_runs": app.store.latest(5),
                    "ai_used": False,
                })
                return
            if path.path == "/api/bridge/watches":
                self._json(HTTPStatus.OK, app.list_watches())
                return
            if path.path.startswith("/api/bridge/runs/"):
                result = app.store.get(path.path.rsplit("/", 1)[-1])
                self._json(HTTPStatus.OK if result else HTTPStatus.NOT_FOUND, result or {"error": "No encontrado"})
                return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Ruta no encontrada"})

        def do_POST(self) -> None:
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "No autorizado"})
                return
            try:
                path = urlparse(self.path).path
                payload = self._payload()
                if path == "/api/bridge/run":
                    self._json(HTTPStatus.OK, app.execute(payload))
                    return
                if path == "/api/bridge/ai/analyze":
                    self._json(HTTPStatus.OK, app.analyze_with_haiku())
                    return
                if path == "/api/bridge/watch/run":
                    self._json(HTTPStatus.OK, app.run_watchers())
                    return
                if path == "/api/bridge/reports/send-calendar":
                    json_path = Path(app.reports_dir) / "ultimas_alertas_altas.json"
                    if not json_path.exists():
                        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "No hay reporte generado aún"})
                        return
                    report_data = json.loads(json_path.read_text(encoding="utf-8"))
                    alerts = report_data.get("alerts", [])
                    title_report = report_data.get("title", "Cables relevantes")
                    generated_at = report_data.get("generated_at", "")
                    active_recipients = [r["email"] for r in app.recipients.list(enabled_only=True)]
                    if not active_recipients:
                        self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "No hay suscriptores activos"})
                        return
                    from .watcher import alert_title, build_alert_text
                    from .google_calendar import publish_calendar_alert

                    class _FakeItem:
                        def __init__(self, d):
                            self.title = d.get("title", "")
                            self.subtitle = d.get("subtitle", "")
                            self.summary = d.get("summary", "")
                            self.source = d.get("source", "")
                            self.mentions = int(d.get("mentions", 1) or 1)
                            self.relevance_score = d.get("relevance_score", 0)
                            self.url = d.get("url", "")

                    from datetime import datetime
                    fake_items = [_FakeItem(a) for a in alerts]
                    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
                    subject = f"CABLE DE NOTICIAS · {date_str}"
                    body = build_alert_text("Resumen editorial consolidado", fake_items, len(fake_items), 20, "alta")
                    result = publish_calendar_alert(active_recipients, subject, body, "alta")
                    ok = result.get("status") == "created"
                    self._json(HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY, {"ok": ok, "calendar": result})
                    return
                if path == "/api/bridge/reports/open":
                    folder = Path(app.reports_dir)
                    folder.mkdir(parents=True, exist_ok=True)
                    if os.name != "nt":
                        raise ValueError("Abrir la carpeta está disponible solamente en Windows")
                    subprocess.Popen(["explorer.exe", str(folder.resolve())])
                    self._json(HTTPStatus.OK, {"ok": True, "folder": str(folder.resolve())})
                    return
                if path == "/api/bridge/reports/send-mailing":
                    products = {
                        "general": ("mailing.html", "Cables relevantes"),
                        "politico": ("feed-politico.html", "Cable político y económico"),
                        "agenda": ("feed-agenda.html", "Agenda legislativa"),
                        "boletin": ("feed-boletin.html", "Boletín Oficial"),
                        "geopolitica": ("feed-geopolitica.html", "Geopolítica"),
                    }
                    product = str(payload.get("product", "general")).strip().casefold()
                    if product not in products:
                        raise ValueError("Producto de distribución no válido")
                    filename, product_name = products[product]
                    mailing_path = Path(app.reports_dir) / filename
                    if not mailing_path.is_file():
                        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "No hay mailing generado aún"})
                        return
                    selected_ids = {int(value) for value in payload.get("recipient_ids", []) if str(value).isdigit()}
                    recipient_rows = app.recipients.list(enabled_only=True)
                    if selected_ids:
                        recipient_rows = [item for item in recipient_rows if int(item["id"]) in selected_ids]
                    recipients = [item["email"] for item in recipient_rows]
                    if not recipients:
                        self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "No hay destinatarios activos"})
                        return
                    # Un mismo cable no se reenvía: evita duplicados y que el
                    # mailing termine clasificado como spam. Un nuevo rastreo
                    # produce un contenido distinto y vuelve a habilitarlo.
                    html_body = mailing_path.read_text(encoding="utf-8")
                    normalized = re.sub(r"Actualizado [^<]+", "", html_body)
                    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                    signature = f"{product}:{digest}:{','.join(sorted(recipients))}"
                    delivery_state = Path(app.reports_dir) / "mailing_delivery.json"
                    try:
                        previous = json.loads(delivery_state.read_text(encoding="utf-8"))
                        previous_at = datetime.fromisoformat(str(previous.get("sent_at", "")).replace("Z", "+00:00"))
                    except (OSError, ValueError, json.JSONDecodeError):
                        previous, previous_at = {}, None
                    if previous.get("signature") == signature and previous_at and datetime.now(timezone.utc) - previous_at < timedelta(hours=24):
                        self._json(HTTPStatus.CONFLICT, {"ok": False, "error": "Este cable ya fue enviado. Se habilitará al generarse un rastreo con novedades."})
                        return
                    from .notifier import send_email_alert
                    subject = f"CONSULTORA DIAGONALES · {product_name} · " + datetime.now().strftime("%d/%m/%Y %H:%M")
                    deliveries = send_email_alert(recipients, subject, "Cables relevantes de Consultora Diagonales.", html_body)
                    for delivery in deliveries:
                        app.recipients.log_delivery(delivery["email"], "mailing", subject, delivery["status"], delivery["error"])
                    ok = bool(deliveries) and all(item["status"] == "sent" for item in deliveries)
                    if ok:
                        delivery_state.write_text(json.dumps({"signature": signature, "sent_at": datetime.now(timezone.utc).isoformat(), "recipients": recipients, "product": product}, ensure_ascii=False), encoding="utf-8")
                    self._json(HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY, {"ok": ok, "deliveries": deliveries})
                    return
                if path == "/api/bridge/watches":
                    watch = app.add_watch(payload)
                    self._json(HTTPStatus.CREATED, {"ok": True, "watch": watch})
                    return
                if path == "/api/bridge/recipients":
                    recipient = app.recipients.add(str(payload.get("email", "")), str(payload.get("name", "")))
                    self._json(HTTPStatus.CREATED, {"ok": True, "recipient": recipient, "delivery_mode": "rss", "rss_url": "/reports/rss.xml"})
                    return
                if path in {"/api/bridge/email/test", "/api/bridge/calendar/test"}:
                    recipient_id = int(payload.get("recipient_id", 0))
                    recipient = app.recipients.get(recipient_id)
                    if not recipient.get("enabled", False):
                        self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "El destinatario está pausado"})
                        return
                    subject = "CABLE DE NOTICIAS CONSULTORA DIAGONALES: PRUEBA"
                    result = publish_calendar_alert(
                        [recipient["email"]],
                        subject,
                        "La configuración de alertas en Google Calendar funciona correctamente.",
                        "baja",
                    )
                    for delivery in result.get("subscribers", []):
                        app.recipients.log_delivery(delivery["email"], "test", subject, delivery["status"], delivery["error"])
                    ok = result.get("status") == "created"
                    self._json(HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY, {"ok": ok, "calendar": result})
                    return
                if path == "/api/bridge/recipients/send-last-run":
                    recipient_id = int(payload.get("recipient_id", 0))
                    recipient = app.recipients.get(recipient_id)
                    runs = app.store.latest(10)
                    selected_run = next(
                        (r for r in runs if r.get("watch_label") == "Búsqueda manual" or r.get("watch_id") == "manual"),
                        None,
                    )
                    if not selected_run and runs:
                        selected_run = runs[0]
                    if not selected_run:
                        self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "No hay rastreos recientes para enviar"})
                        return
                    from datetime import datetime
                    results = selected_run.get("results", [])
                    total = selected_run.get("total_matched", len(results))
                    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
                    subject = f"CABLE DE NOTICIAS · {date_str}"
                    date_long = datetime.now().strftime("%d de %B de %Y, %H:%M hs")
                    lines = [f"CABLE DE NOTICIAS · {date_long}", f"{total} artículo(s) detectado(s).", ""]
                    for idx, item in enumerate(results[:20], 1):
                        lines.append(f"{idx}. {item.get('title', 'Sin título')}")
                        src = item.get('source', '')
                        mentions = item.get('mentions', 1)
                        lines.append(f"Fuente: {src} · {mentions} menciones")
                        subtitle = str(item.get("ai_summary") or item.get("subtitle") or "").strip()
                        analysis = str(item.get("political_analysis") or "").strip()
                        if subtitle:
                            lines.append(f"Bajada: {subtitle[:240]}")
                        if analysis:
                            lines.append(f"Análisis político: {analysis[:240]}")
                        if item.get("url"):
                            lines.append(item["url"])
                        alternate_urls = item.get("alternate_urls", [])
                        if isinstance(alternate_urls, list):
                            lines.extend(str(url) for url in alternate_urls if str(url).strip())
                        lines.append("")
                    if total > 20:
                        lines.append(f"+ {total - 20} artículo(s) adicional(es).")
                    body = "\n".join(lines).strip()
                    result = publish_calendar_alert([recipient["email"]], subject, body, "alta")
                    for delivery in result.get("subscribers", []):
                        app.recipients.log_delivery(delivery["email"], "manual-send", subject, delivery["status"], delivery["error"])
                    ok = result.get("status") == "created"
                    self._json(HTTPStatus.OK if ok else HTTPStatus.BAD_GATEWAY, {"ok": ok, "calendar": result})
                    return
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Ruta no encontrada"})
            except BooleanSyntaxError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc), "type": "boolean_syntax"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc), "type": "bad_request"})
            except Exception as exc:
                self._json(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc), "type": "source_error"})

        def do_PATCH(self) -> None:
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "No autorizado"})
                return
            try:
                path = urlparse(self.path).path
                if path.startswith("/api/bridge/watches/"):
                    payload = self._payload()
                    watch = app.update_watch(path.rstrip("/").rsplit("/", 1)[-1], payload)
                    self._json(HTTPStatus.OK, {"ok": True, "watch": watch})
                    return
                if not path.startswith("/api/bridge/recipients/"):
                    self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Ruta no encontrada"})
                    return
                payload = self._payload()
                enabled = payload.get("enabled")
                if enabled is not None and not isinstance(enabled, bool):
                    raise ValueError("'enabled' debe ser booleano")
                recipient = app.recipients.update(
                    self._recipient_id(path), name=payload.get("name"), enabled=enabled
                )
                self._json(HTTPStatus.OK, {"ok": True, "recipient": recipient, "delivery_mode": "rss", "rss_url": "/reports/rss.xml"})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": str(exc)})

        def do_DELETE(self) -> None:
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "No autorizado"})
                return
            try:
                path = urlparse(self.path).path
                if path.startswith("/api/bridge/watches/"):
                    app.delete_watch(path.rstrip("/").rsplit("/", 1)[-1])
                    self._json(HTTPStatus.OK, {"ok": True})
                    return
                if not path.startswith("/api/bridge/recipients/"):
                    self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Ruta no encontrada"})
                    return
                recipient = app.recipients.get(self._recipient_id(path))
                app.recipients.delete(recipient["id"])
                subscription = remove_calendar_subscriber(recipient["email"]) if google_calendar_status()["configured"] else None
                self._json(HTTPStatus.OK, {"ok": True, "calendar_subscription": subscription})
            except (ValueError, KeyError) as exc:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": str(exc)})

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"[{self.log_date_time_string()}] {self.client_address[0]} {fmt % args}")

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="API local del Rastreador OSINT-BOOLEANO")
    parser.add_argument("--host", default=os.getenv("BRIDGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("BRIDGE_PORT", "8765")))
    parser.add_argument("--config", default=str(PACKAGE_ROOT / "config" / "sources.json"))
    parser.add_argument("--aliases", default=str(PACKAGE_ROOT / "config" / "aliases.json"))
    parser.add_argument("--database", default=str(PACKAGE_ROOT / "data" / "bridge.sqlite3"))
    parser.add_argument("--watches", default=str(PACKAGE_ROOT / "config" / "watch_queries.json"))
    parser.add_argument("--alerts-dir", default=str(PACKAGE_ROOT / "alerts"))
    parser.add_argument("--reports-dir", default=str(PACKAGE_ROOT / "reports"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = BridgeApp(args.config, args.aliases, args.database, args.watches, args.alerts_dir, args.reports_dir)
    if args.host not in {"127.0.0.1", "::1", "localhost"} and not app.token:
        raise SystemExit("Acceso móvil rechazado: configure una clave antes de escuchar en la red.")
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"Rastreador OSINT-BOOLEANO escuchando en http://{args.host}:{args.port}")
    ai_enabled = bool(app.config.get("ai", {}).get("enabled", False))
    try:
        ai_ready = ai_enabled and bool(app._load_api_key())
    except ValueError:
        ai_ready = False
    print(f"IA: {'Claude Haiku habilitado' if ai_ready else 'Claude Haiku sin clave'} | Suscripciones: ninguna")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
