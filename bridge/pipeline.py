from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .boolean_parser import coverage, discovery_queries, normalize_text, parse
from .editorial import classify_editorial_desk, is_editorially_in_scope, is_geopolitical_item
from .ai import enrich_with_claude
from .models import Evidence, RunResult, utc_now
from .sources import discover
from .storage import RunStore


TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_PARAMS
    ]
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), urlencode(query), ""))


def title_fingerprint(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", normalize_text(title))
    return " ".join(words)


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def within_window(item: Evidence, since_days: int) -> bool:
    published = parse_date(item.published_at)
    if published is None:
        return True
    return published >= datetime.now(timezone.utc) - timedelta(days=since_days)


def _contains_policy_term(text: str, term: str) -> bool:
    normalized = normalize_text(term)
    if not normalized:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", text) is not None


def item_allowed_by_policy(item: Evidence | Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    """Aplica el encuadre editorial configurado antes de guardar o alertar."""
    policy = config.get("content_policy", {}) if isinstance(config, Mapping) else {}
    if not isinstance(policy, Mapping) or not policy.get("enabled", False):
        return True
    if isinstance(item, Mapping):
        values = (
            item.get("title", ""),
            item.get("subtitle", ""),
            item.get("summary", ""),
            item.get("source", ""),
            item.get("domain", ""),
        )
        domain = str(item.get("domain", "")).casefold().removeprefix("www.")
    else:
        values = (item.title, item.subtitle, item.summary, item.source, item.domain)
        domain = item.domain.casefold().removeprefix("www.")
    text = normalize_text(" ".join(str(value or "") for value in values))
    excluded_terms = policy.get("excluded_terms", [])
    if isinstance(excluded_terms, list) and any(_contains_policy_term(text, str(term)) for term in excluded_terms):
        return False
    if not policy.get("require_argentina_context", False):
        return True
    domestic_domains = policy.get("domestic_domain_suffixes", [".gob.ar", ".gov.ar"])
    if isinstance(domestic_domains, list) and any(
        domain == str(suffix).lstrip(".").casefold() or domain.endswith(str(suffix).casefold())
        for suffix in domestic_domains
        if str(suffix).strip()
    ):
        return True
    domestic_markers = policy.get("argentina_markers", [])
    return isinstance(domestic_markers, list) and any(
        _contains_policy_term(text, str(marker)) for marker in domestic_markers
    )


def is_duplicate(left: Evidence, right: Evidence) -> bool:
    if canonical_url(left.url) == canonical_url(right.url):
        return True
    a, b = title_fingerprint(left.title), title_fingerprint(right.title)
    return bool(a and b and SequenceMatcher(None, a, b).ratio() >= 0.92)


def deduplicate(items: list[Evidence]) -> list[Evidence]:
    merged: list[Evidence] = []
    for item in items:
        existing = next((candidate for candidate in merged if is_duplicate(candidate, item)), None)
        if existing is None:
            item.corroborating_sources = [item.source]
            merged.append(item)
            continue
        existing.mentions += 1
        existing.corroborating_sources = sorted(set(existing.corroborating_sources + [item.source]))
        if existing.domain == "news.google.com" and item.domain and item.domain != "news.google.com":
            if existing.url:
                existing.alternate_urls = sorted(set(existing.alternate_urls + [existing.url]))
            existing.url = item.url
            existing.domain = item.domain
            existing.source = item.source
        elif item.url and canonical_url(item.url) != canonical_url(existing.url):
            existing.alternate_urls = sorted(set(existing.alternate_urls + [item.url]))
        if len(item.summary) > len(existing.summary):
            existing.summary = item.summary
        if not existing.published_at and item.published_at:
            existing.published_at = item.published_at
    return merged


def score_item(
    item: Evidence,
    root,
    aliases: Mapping[str, Sequence[str]],
    official_domains: set[str],
    official_domain_suffixes: Sequence[str] = (),
) -> None:
    relevance = round(coverage(root, item.searchable_text(), aliases) * 55)
    domain = item.domain.casefold().removeprefix("www.")
    item.official = any(domain == value or domain.endswith("." + value) for value in official_domains) or any(
        domain.endswith(str(suffix).casefold()) for suffix in official_domain_suffixes if str(suffix).strip()
    )
    authority = 20 if item.official else 7
    independent_sources = len(set(item.corroborating_sources))
    corroboration = min(15, max(0, independent_sources - 1) * 5)
    published = parse_date(item.published_at)
    recency = 5
    if published:
        age = max(0.0, (datetime.now(timezone.utc) - published).total_seconds() / 86400)
        recency = 10 if age <= 1 else 7 if age <= 3 else 4
    item.relevance_score = min(100, relevance + authority + corroboration + recency)
    if item.official or (independent_sources >= 3 and item.relevance_score >= 75):
        item.confidence = "alta"
    elif independent_sources >= 2 or item.relevance_score >= 60:
        item.confidence = "media"
    else:
        item.confidence = "baja"
    if not item.subtitle:
        summary = re.sub(r"\s+", " ", item.summary).strip()
        title = re.sub(r"\s+", " ", item.title).strip()
        if title and summary.casefold().startswith(title.casefold()):
            summary = summary[len(title):].lstrip(" \t\r\n:–—-|.")
        sentence = re.split(r"(?<=[.!?])\s+", summary, maxsplit=1)[0] if summary else ""
        item.subtitle = sentence[:240] or f"{item.source} · {item.mentions} mención(es)"


def run_pipeline(
    query: str,
    source_config: dict[str, Any],
    aliases: Mapping[str, Sequence[str]] | None = None,
    since_days: int = 7,
    max_results: int = 100,
    store: RunStore | None = None,
    watch_id: str = "",
    watch_label: str = "",
) -> RunResult:
    started_at = utc_now()
    root = parse(query)
    aliases = aliases or {}
    pivots = discovery_queries(query, root, aliases, int(source_config.get("max_discovery_queries", 12)))
    raw, errors = discover(
        source_config,
        pivots,
        int(source_config.get("max_workers", 6)),
        int(source_config.get("max_per_job", 100)),
    )
    candidates = [item for item in raw if within_window(item, since_days)]
    geopolitics_watch = "geopolit" in normalize_text(f"{watch_id} {watch_label}")
    matched = [
        item
        for item in candidates
        if root.evaluate(item.searchable_text(), aliases)
        and (
            is_geopolitical_item(item)
            if geopolitics_watch
            else item_allowed_by_policy(item, source_config) and is_editorially_in_scope(item)
        )
    ]
    results = deduplicate(matched)
    authority_values = source_config.get("high_authority_domains", source_config.get("official_domains", []))
    official_domains = {value.casefold().removeprefix("www.") for value in authority_values}
    official_domain_suffixes = tuple(source_config.get("official_domain_suffixes", []))
    for item in results:
        score_item(item, root, aliases, official_domains, official_domain_suffixes)
        item.desk = classify_editorial_desk(item)
    results.sort(key=lambda item: (item.official, item.relevance_score, item.published_at or ""), reverse=True)
    monitor_ids = {str(item.get("id", "")) for item in source_config.get("official_monitors", []) if item.get("enabled", True)}
    reserved: list[Evidence] = []
    for monitor_id in monitor_ids:
        candidates_for_monitor = [item for item in results if item.discovered_by == monitor_id and item not in reserved]
        reserved.extend(candidates_for_monitor[:5])
        if len(reserved) >= max_results:
            break
    if reserved:
        results = reserved[:max_results] + [item for item in results if item not in reserved]
    selected = results[:max_results]
    ai_used, ai_errors = enrich_with_claude(selected, query, source_config)
    errors.extend(ai_errors)
    completed_at = utc_now()
    run_id = hashlib.sha256(f"{query}|{started_at}".encode()).hexdigest()[:16]
    output = RunResult(
        run_id=run_id,
        query=query,
        started_at=started_at,
        completed_at=completed_at,
        discovery_queries=pivots,
        total_discovered=len(raw),
        total_matched=len(results),
        results=selected,
        errors=errors,
        ai_used=ai_used,
        watch_id=watch_id,
        watch_label=watch_label,
    )
    if store:
        store.save(output)
    return output
