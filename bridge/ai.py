from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable
import urllib.error
import urllib.request

from .models import Evidence

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _api_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    for candidate in (PACKAGE_ROOT / ".env", PACKAGE_ROOT.parent / ".env"):
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _compact(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split()).strip()[:limit].rstrip()


def _json_from_text(value: str) -> dict[str, Any]:
    value = value.strip()
    if value.startswith("```"):
        value = value.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("La respuesta de Claude no es un objeto JSON")
    return result


def enrich_with_claude(items: Iterable[Evidence], query: str, config: dict[str, Any]) -> tuple[bool, list[dict[str, str]]]:
    settings = config.get("ai", {}) if isinstance(config.get("ai", {}), dict) else {}
    if not settings.get("enabled", False):
        return False, []
    key = _api_key()
    if not key:
        return False, [{"source": "claude", "error": "ANTHROPIC_API_KEY no configurada"}]
    model = str(settings.get("model") or DEFAULT_MODEL)
    maximum = max(1, min(int(settings.get("max_items_per_run", 20)), 100))
    errors: list[dict[str, str]] = []
    used = False
    for item in list(items)[:maximum]:
        prompt = f'''Sos analista político de Consultora Diagonales (Argentina). Evaluá una noticia según la consulta del monitor.

Consulta: {query}
Título: {item.title}
Fuente: {item.source}
Texto disponible: {item.subtitle or item.summary}

Respondé exclusivamente JSON válido, sin Markdown:
{{"bajada":"resumen factual, neutral y útil para un cable; máximo 240 caracteres","analisis_politico":"lectura política breve, prudente y basada solo en el texto; máximo 240 caracteres"}}
No inventes datos. Si falta evidencia, indicá la limitación de manera breve.'''
        payload = json.dumps({"model": model, "max_tokens": 220, "temperature": 0, "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        request = urllib.request.Request("https://api.anthropic.com/v1/messages", data=payload, method="POST", headers={"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(request, timeout=float(settings.get("timeout_seconds", 30))) as response:
                answer = json.loads(response.read().decode("utf-8"))
            text = "".join(block.get("text", "") for block in answer.get("content", []) if block.get("type") == "text")
            content = _json_from_text(text)
            item.ai_summary = _compact(content.get("bajada"))
            item.political_analysis = _compact(content.get("analisis_politico"))
            if item.ai_summary:
                item.subtitle = item.ai_summary
            used = True
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("error", {}).get("message", detail)
            except json.JSONDecodeError:
                pass
            errors.append({"source": "claude", "error": str(detail)[:500]})
        except (urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"source": "claude", "error": str(exc)[:500]})
    return used, errors
