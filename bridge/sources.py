from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
import html
from html.parser import HTMLParser
import re
import socket
import time
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import Evidence


USER_AGENT = "RastreadorOSINTBooleano/1.3.8 (+public-source-monitoring; no-ai)"
_AGENDA_CACHE: dict[str, tuple[float, list[Evidence]]] = {}
_BYTES_CACHE: dict[str, tuple[float, bytes]] = {}


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", html.unescape(value))
    return re.sub(r"\s+", " ", value).strip()


def domain_of(url: str) -> str:
    return (urlparse(url).hostname or "").casefold().removeprefix("www.")


def _text(node: ET.Element, names: Iterable[str]) -> str:
    for name in names:
        found = node.find(name)
        if found is not None and found.text:
            return found.text.strip()
    return ""


def _published(value: str) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, OverflowError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return value


def parse_feed(payload: bytes, source_name: str, discovered_by: str) -> list[Evidence]:
    root = ET.fromstring(payload)
    results: list[Evidence] = []
    items = root.findall(".//item")
    if items:
        for item in items:
            url = _text(item, ["link"])
            source_node = item.find("source")
            source_url = source_node.attrib.get("url", "") if source_node is not None else ""
            results.append(
                Evidence(
                    title=strip_html(_text(item, ["title"])),
                    url=url,
                    source=strip_html(_text(item, ["source"])) or source_name,
                    summary=strip_html(_text(item, ["description", "summary"])),
                    published_at=_published(_text(item, ["pubDate", "published", "date"])),
                    discovered_by=discovered_by,
                    domain=domain_of(source_url) or domain_of(url),
                )
            )
        return [item for item in results if item.title and item.url]

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//atom:entry", ns) + root.findall(".//entry"):
        link = entry.find("atom:link", ns) or entry.find("link")
        url = link.attrib.get("href", "") if link is not None else ""
        title = _text(entry, ["{http://www.w3.org/2005/Atom}title", "title"])
        summary = _text(
            entry,
            ["{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content", "summary", "content"],
        )
        published = _text(
            entry,
            ["{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated", "published", "updated"],
        )
        results.append(
            Evidence(
                title=strip_html(title),
                url=url,
                source=source_name,
                summary=strip_html(summary),
                published_at=_published(published),
                discovered_by=discovered_by,
                domain=domain_of(url),
            )
        )
    return [item for item in results if item.title and item.url]


def fetch_bytes(url: str, timeout: float = 15.0) -> bytes:
    cached = _BYTES_CACHE.get(url)
    if cached and time.monotonic() - cached[0] < 300:
        return cached[1]
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.5"})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read()
    _BYTES_CACHE[url] = (time.monotonic(), payload)
    return payload


def _catalog_domains(group: dict[str, Any]) -> list[str]:
    """Lee el catálogo público de fuentes sin convertir redes o buscadores en rastreo automático."""
    configured = group.get("domains", [])
    if isinstance(configured, list) and configured:
        raw_domains = [str(value) for value in configured]
    else:
        catalog = str(group.get("catalog_path", "")).strip()
        if not catalog:
            return []
        path = Path(catalog)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        raw_domains = [domain_of(match) for match in re.findall(r"https?://[^\s\]\)\>`\"']+", text)]

    excluded = {
        str(value).casefold().removeprefix("www.")
        for value in group.get("exclude_domains", [])
        if str(value).strip()
    }
    domains: list[str] = []
    for value in raw_domains:
        domain = domain_of(value) if "://" in value else value.casefold().removeprefix("www.").strip("/ ")
        if not domain or domain in excluded or any(domain.endswith("." + item) for item in excluded):
            continue
        if domain not in domains:
            domains.append(domain)
    return domains


def _source_group_queries(group: dict[str, Any], query: str) -> list[str]:
    domains = _catalog_domains(group)
    if not domains:
        return []
    batch_size = max(1, min(int(group.get("max_domains_per_query", 12)), 20))
    result: list[str] = []
    for start in range(0, len(domains), batch_size):
        sites = " OR ".join(f"site:{domain}" for domain in domains[start:start + batch_size])
        result.append(f"({query}) ({sites})")
    return result


@dataclass(frozen=True)
class FetchJob:
    name: str
    url: str
    query: str
    kind: str = "feed"


class AgendaTableParser(HTMLParser):
    """Extrae filas de las agendas oficiales sin depender de selectores externos."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.active_table = False
        self.table_depth = 0
        self.in_row = False
        self.cell_depth = 0
        self.strong_depth = 0
        self.cells: list[str] = []
        self.cell_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.link_href = ""
        self.link_parts: list[str] = []
        self.strong_parts: list[str] = []
        self.rows: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "table":
            if self.active_table:
                self.table_depth += 1
            elif attributes.get("id") == "agendaComisiones" or "reuniones previstas" in attributes.get("summary", "").casefold():
                self.active_table = True
                self.table_depth = 1
            return
        if not self.active_table:
            return
        if tag == "tr":
            self.in_row = True
            self.cells, self.links, self.strong_parts = [], [], []
        elif self.in_row and tag in {"td", "th"}:
            self.cell_depth += 1
            self.cell_parts = []
        elif self.in_row and tag == "a":
            self.link_href = attributes.get("href", "").strip()
            self.link_parts = []
        elif self.in_row and tag == "strong":
            self.strong_depth += 1

    def handle_data(self, data: str) -> None:
        if not self.in_row:
            return
        if self.cell_depth:
            self.cell_parts.append(data)
        if self.link_href:
            self.link_parts.append(data)
        if self.strong_depth:
            self.strong_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.active_table:
            self.table_depth -= 1
            if self.table_depth <= 0:
                self.active_table = False
            return
        if not self.active_table:
            return
        if self.in_row and tag in {"td", "th"} and self.cell_depth:
            self.cells.append(strip_html(" ".join(self.cell_parts)))
            self.cell_depth -= 1
        elif self.in_row and tag == "a" and self.link_href:
            self.links.append((self.link_href, strip_html(" ".join(self.link_parts))))
            self.link_href, self.link_parts = "", []
        elif self.in_row and tag == "strong" and self.strong_depth:
            self.strong_depth -= 1
        elif tag == "tr" and self.in_row:
            if any(self.cells):
                self.rows.append({
                    "cells": self.cells[:],
                    "links": self.links[:],
                    "strong": strip_html(" ".join(self.strong_parts)),
                })
            self.in_row = False


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)

    def text(self) -> str:
        return strip_html(" ".join(self.parts))


def _fetch_visible_text(url: str, timeout: float) -> str:
    parser = VisibleTextParser()
    parser.feed(fetch_bytes(url, timeout).decode("utf-8", "replace"))
    return parser.text()


def fetch_official_agenda(job: FetchJob, timeout: float) -> list[Evidence]:
    cached = _AGENDA_CACHE.get(job.url)
    if cached and time.monotonic() - cached[0] < 300:
        return deepcopy(cached[1])
    parser = AgendaTableParser()
    parser.feed(fetch_bytes(job.url, timeout).decode("utf-8", "replace"))
    items: list[Evidence] = []
    current_day = ""
    senate = "senado.gob.ar" in domain_of(job.url)
    senate_detail_requests = 0
    for row in parser.rows:
        cells = row["cells"]
        links = row["links"]
        if senate:
            if len(cells) < 3 or cells[0].casefold() == "comisión":
                continue
            direct = urljoin(job.url, links[0][0].strip()) if links else job.url
            detail = ""
            try:
                if senate_detail_requests:
                    time.sleep(2.0)
                detail = _fetch_visible_text(direct, timeout)
                senate_detail_requests += 1
                marker = detail.casefold().find("se informa")
                if marker >= 0:
                    detail = detail[marker:]
            except Exception:
                detail = ""
            summary = detail[:1800] or f"Agenda confirmada de {cells[0]}. {cells[1]}."
            items.append(Evidence(
                title=f"Senado · Comisión {cells[0]}",
                subtitle=cells[1],
                url=direct,
                source="Honorable Senado de la Nación",
                summary=summary,
                discovered_by="agenda-oficial-senado",
                domain=domain_of(direct),
            ))
            continue

        if len(cells) == 1:
            current_day = cells[0]
            continue
        if len(cells) < 2:
            continue
        commission_links = [text.rstrip(" ,") for href, text in links if "/comisiones/permanentes/" in href]
        commission = ", ".join(dict.fromkeys(filter(None, commission_links))) or row.get("strong", "")
        commission = commission or cells[1].split(". ", 1)[0][:140]
        direct = next((urljoin(job.url, href) for href, _text in links if href.casefold().endswith(".pdf")), job.url)
        subtitle = " · ".join(value for value in (current_day, cells[0]) if value)
        summary = cells[1]
        items.append(Evidence(
            title=f"Diputados · Comisión {commission}",
            subtitle=subtitle,
            url=direct,
            source="Honorable Cámara de Diputados de la Nación",
            summary=summary[:1800],
            discovered_by="agenda-oficial-diputados",
            domain=domain_of(direct),
        ))
    _AGENDA_CACHE[job.url] = (time.monotonic(), deepcopy(items))
    return items


def build_jobs(config: dict[str, Any], queries: list[str]) -> list[FetchJob]:
    jobs: list[FetchJob] = []
    google = config.get("google_news", {})
    if google.get("enabled", True):
        language = google.get("language", "es-419")
        country = google.get("country", "AR")
        edition = google.get("edition", f"{country}:es-419")
        for query in queries:
            url = (
                "https://news.google.com/rss/search?q="
                f"{quote_plus(query)}&hl={quote_plus(language)}&gl={quote_plus(country)}&ceid={quote_plus(edition)}"
            )
            jobs.append(FetchJob("Google News", url, query))
    for feed in config.get("feeds", []):
        if feed.get("enabled", True) and feed.get("url"):
            jobs.append(FetchJob(feed.get("name", domain_of(feed["url"])), feed["url"], "feed-directo"))
    google = config.get("google_news", {})
    language = google.get("language", "es-419")
    country = google.get("country", "AR")
    edition = google.get("edition", f"{country}:es-419")
    for monitor in config.get("official_monitors", []):
        if monitor.get("enabled", True) and monitor.get("query"):
            url = (
                "https://news.google.com/rss/search?q="
                f"{quote_plus(monitor['query'])}&hl={quote_plus(language)}&gl={quote_plus(country)}&ceid={quote_plus(edition)}"
            )
            jobs.append(FetchJob(monitor.get("name", "Fuente oficial"), url, monitor.get("id", "fuente-oficial")))
    for group in config.get("source_groups", []):
        if not group.get("enabled", True):
            continue
        group_id = str(group.get("id", "catalogo-fuentes")).strip() or "catalogo-fuentes"
        group_name = str(group.get("name", "Catálogo de fuentes")).strip() or "Catálogo de fuentes"
        # El catálogo se acota con la expresión editorial original. Unir todos
        # los pivotes podía generar URLs de Google News demasiado largas y
        # devolvía resultados genéricos ajenos al pedido.
        primary_query = queries[0] if queries else ""
        for index, scoped_query in enumerate(_source_group_queries(group, primary_query), 1):
            url = (
                "https://news.google.com/rss/search?q="
                f"{quote_plus(scoped_query)}&hl={quote_plus(language)}&gl={quote_plus(country)}&ceid={quote_plus(edition)}"
            )
            jobs.append(FetchJob(group_name, url, f"{group_id}-{index}"))
    for page in config.get("agenda_pages", []):
        if page.get("enabled", True) and page.get("url"):
            jobs.append(FetchJob(page.get("name", domain_of(page["url"])), page["url"], "agenda-oficial", "agenda_html"))
    return jobs


def discover(
    config: dict[str, Any],
    queries: list[str],
    max_workers: int = 6,
    max_per_job: int = 100,
) -> tuple[list[Evidence], list[dict[str, str]]]:
    jobs = build_jobs(config, queries)
    results: list[Evidence] = []
    errors: list[dict[str, str]] = []
    socket.setdefaulttimeout(float(config.get("timeout_seconds", 15)))

    def run(job: FetchJob) -> list[Evidence]:
        if job.kind == "agenda_html":
            return fetch_official_agenda(job, float(config.get("timeout_seconds", 15)))[:max_per_job]
        return parse_feed(fetch_bytes(job.url, float(config.get("timeout_seconds", 15))), job.name, job.query)[:max_per_job]

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 16))) as pool:
        future_jobs = {pool.submit(run, job): job for job in jobs}
        for future in as_completed(future_jobs):
            job = future_jobs[future]
            try:
                results.extend(future.result())
            except Exception as exc:  # cada fuente falla de forma aislada
                errors.append({"source": job.name, "query": job.query, "error": str(exc)[:500]})
    return results, errors
