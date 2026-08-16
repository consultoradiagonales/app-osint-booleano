from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html as _html
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .windows_credentials import get_google_calendar_refresh_token


CALENDAR_API = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ORGANIZER_EMAIL = "info.consultoradiagonales@gmail.com"


class GoogleCalendarError(RuntimeError):
    pass


def _setting(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is not None:
        return value
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                return str(winreg.QueryValueEx(key, name)[0])
        except (OSError, ValueError):
            pass
    return default


def _oauth_client() -> tuple[str, str]:
    path = Path(_setting("OSINT_GCAL_CLIENT_SECRET_PATH"))
    if not path.is_file():
        raise GoogleCalendarError("Falta autorizar Google Calendar en esta PC")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        client = payload.get("installed") or payload.get("web") or {}
        client_id = str(client["client_id"])
        client_secret = str(client["client_secret"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise GoogleCalendarError("La configuración OAuth de Google Calendar no es válida") from exc
    return client_id, client_secret


def google_calendar_status() -> dict[str, object]:
    calendar_id = _setting("OSINT_GCAL_CALENDAR_ID").strip()
    organizer = _setting("OSINT_GCAL_ORGANIZER", ORGANIZER_EMAIL).strip().lower()
    client_path = Path(_setting("OSINT_GCAL_CLIENT_SECRET_PATH"))
    token = get_google_calendar_refresh_token()
    return {
        "configured": bool(calendar_id and client_path.is_file() and token),
        "organizer": organizer,
        "calendar_id": calendar_id,
        "calendar_name": _setting("OSINT_GCAL_CALENDAR_NAME", "CABLE DE NOTICIAS CONSULTORA DIAGONALES"),
        "delivery_mode": "calendar_only",
        "email_alerts": False,
    }


def _json_request(url: str, *, method: str = "GET", data: dict[str, Any] | None = None, token: str = "") -> dict[str, Any]:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise GoogleCalendarError(detail or f"Google Calendar respondió HTTP {exc.code}") from exc
    except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise GoogleCalendarError(f"No se pudo conectar con Google Calendar: {exc}") from exc


def _access_token() -> str:
    refresh_token = get_google_calendar_refresh_token()
    if not refresh_token:
        raise GoogleCalendarError("Falta autorizar Google Calendar en esta PC")
    client_id, client_secret = _oauth_client()
    payload = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    request = Request(TOKEN_URL, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(request, timeout=25) as response:
            token = str(json.loads(response.read().decode("utf-8"))["access_token"])
    except (HTTPError, URLError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise GoogleCalendarError("La autorización de Google Calendar venció o fue revocada") from exc
    return token


def _calendar_id() -> str:
    value = _setting("OSINT_GCAL_CALENDAR_ID").strip()
    if not value:
        raise GoogleCalendarError("Falta seleccionar el calendario de cables")
    return value


def _acl_rules(token: str, calendar_id: str) -> list[dict[str, Any]]:
    payload = _json_request(
        f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/acl?maxResults=250",
        token=token,
    )
    return list(payload.get("items", []))


def sync_calendar_subscribers(recipients: Iterable[str]) -> list[dict[str, str]]:
    addresses = list(dict.fromkeys(str(value).strip().lower() for value in recipients if str(value).strip()))
    if not addresses:
        return []
    token = _access_token()
    calendar_id = _calendar_id()
    rules = _acl_rules(token, calendar_id)
    existing = {
        str(rule.get("scope", {}).get("value", "")).lower(): str(rule.get("id", ""))
        for rule in rules
        if rule.get("scope", {}).get("type") == "user"
    }
    results: list[dict[str, str]] = []
    for email in addresses:
        if email == ORGANIZER_EMAIL or email in existing:
            results.append({"email": email, "status": "subscribed", "error": ""})
            continue
        try:
            _json_request(
                f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/acl?sendNotifications=true",
                method="POST",
                data={"scope": {"type": "user", "value": email}, "role": "reader"},
                token=token,
            )
            results.append({"email": email, "status": "invited", "error": ""})
        except GoogleCalendarError as exc:
            results.append({"email": email, "status": "failed", "error": str(exc)})
    return results


def remove_calendar_subscriber(email: str) -> dict[str, str]:
    address = str(email).strip().lower()
    if not address or address == ORGANIZER_EMAIL:
        return {"email": address, "status": "unchanged", "error": ""}
    token = _access_token()
    calendar_id = _calendar_id()
    rules = _acl_rules(token, calendar_id)
    rule_id = next(
        (
            str(rule.get("id", ""))
            for rule in rules
            if rule.get("scope", {}).get("type") == "user"
            and str(rule.get("scope", {}).get("value", "")).lower() == address
        ),
        "",
    )
    if not rule_id:
        return {"email": address, "status": "removed", "error": ""}
    url = f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/acl/{quote(rule_id, safe='')}"
    request = Request(url, headers={"Authorization": f"Bearer {token}"}, method="DELETE")
    try:
        with urlopen(request, timeout=25):
            pass
        return {"email": address, "status": "removed", "error": ""}
    except (HTTPError, URLError, OSError) as exc:
        return {"email": address, "status": "failed", "error": str(exc)}


def _body_to_html(text: str) -> str:
    parts = re.split(r"(https?://[^\s]+)", text)
    html_parts = []
    for part in parts:
        if re.match(r"https?://", part):
            safe = _html.escape(part, quote=True)
            html_parts.append(f'<a href="{safe}">{safe}</a>')
        else:
            html_parts.append(_html.escape(part))
    return "".join(html_parts).replace("\n", "<br>\n")


def publish_calendar_alert(recipients: Iterable[str], subject: str, body: str, level: str = "alta") -> dict[str, Any]:
    addresses = list(dict.fromkeys(str(value).strip().lower() for value in recipients if str(value).strip()))
    status = google_calendar_status()
    if not status["configured"]:
        return {"status": "skipped", "error": "Google Calendar no está autorizado", "subscribers": []}
    if not addresses:
        return {"status": "skipped", "error": "No hay suscriptores activos", "subscribers": []}
    try:
        subscribers = sync_calendar_subscribers(addresses)
        if not any(item["status"] in {"subscribed", "invited"} for item in subscribers):
            return {"status": "failed", "error": "No se pudo habilitar ningún suscriptor", "subscribers": subscribers}
        token = _access_token()
        now = datetime.now(timezone.utc)
        start = now + timedelta(minutes=2)
        end = start + timedelta(minutes=15)
        first_url = next(iter(re.findall(r"https?://\S+", body)), "")
        color = {"alta": "11", "media": "5", "baja": "2"}.get(str(level).lower(), "1")
        organizer_email = _setting("OSINT_GCAL_ORGANIZER", ORGANIZER_EMAIL).strip().lower()
        attendees = [{"email": addr, "responseStatus": "accepted"} for addr in addresses if addr != organizer_email]
        payload: dict[str, Any] = {
            "summary": subject[:1024],
            "description": _body_to_html(body)[:8000],
            "organizer": {"email": organizer_email, "displayName": "\U0001f4f0 Agencia de noticias C. Diagonales"},
            "creator": {"email": organizer_email, "displayName": "\U0001f4f0 Agencia de noticias C. Diagonales"},
            "start": {"dateTime": start.isoformat(), "timeZone": "America/Argentina/Buenos_Aires"},
            "end": {"dateTime": end.isoformat(), "timeZone": "America/Argentina/Buenos_Aires"},
            "transparency": "transparent",
            "visibility": "default",
            "colorId": color,
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]},
            "guestsCanSeeOtherGuests": False,
        }
        if attendees:
            payload["attendees"] = attendees
        if first_url:
            payload["source"] = {"title": "Fuente del cable", "url": first_url}
        # The shared calendar event and its popup are the delivery channel.
        # Suppress per-event email invitations to avoid recipient spam.
        send_param = "none"
        event = _json_request(
            f"{CALENDAR_API}/calendars/{quote(_calendar_id(), safe='')}/events?sendUpdates={send_param}",
            method="POST",
            data=payload,
            token=token,
        )
        return {
            "status": "created",
            "error": "",
            "event_id": str(event.get("id", "")),
            "event_link": str(event.get("htmlLink", "")),
            "organizer": status["organizer"],
            "subscribers": subscribers,
            "email_alerts": False,
        }
    except GoogleCalendarError as exc:
        return {"status": "failed", "error": str(exc), "subscribers": []}
