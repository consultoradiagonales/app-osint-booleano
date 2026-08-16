from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Evidence:
    title: str
    url: str
    source: str
    subtitle: str = ""
    summary: str = ""
    published_at: str | None = None
    discovered_by: str = ""
    domain: str = ""
    mentions: int = 1
    corroborating_sources: list[str] = field(default_factory=list)
    alternate_urls: list[str] = field(default_factory=list)
    relevance_score: int = 0
    confidence: str = "baja"
    official: bool = False
    ai_summary: str = ""
    political_analysis: str = ""
    desk: str = ""

    def searchable_text(self) -> str:
        # discovered_by describe la ruta de búsqueda, no el contenido de la noticia.
        # Incluirlo hacía que una nota coincidiera sólo porque la consulta estaba
        # guardada como metadato del hallazgo.
        return " ".join((self.title, self.subtitle, self.summary, self.source, self.domain))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    run_id: str
    query: str
    started_at: str
    completed_at: str
    discovery_queries: list[str]
    total_discovered: int
    total_matched: int
    results: list[Evidence]
    errors: list[dict[str, str]] = field(default_factory=list)
    engine: str = "rastreador-osint-booleano/1.3.8"
    ai_used: bool = False
    paid_services_used: bool = False
    watch_id: str = ""
    watch_label: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["results"] = [item.to_dict() for item in self.results]
        return payload


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
