from __future__ import annotations

import base64
from email.message import EmailMessage
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .windows_credentials import get_gmail_refresh_token

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


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


def configured() -> bool:
    return bool(_setting("OSINT_GMAIL_ENABLED").lower() in {"1", "true", "yes", "si"} and _setting("OSINT_GMAIL_CLIENT_SECRET_PATH") and get_gmail_refresh_token())


def _client() -> tuple[str, str]:
    path = Path(_setting("OSINT_GMAIL_CLIENT_SECRET_PATH"))
    data = json.loads(path.read_text(encoding="utf-8"))
    client = data.get("installed") or data.get("web") or {}
    return str(client["client_id"]), str(client["client_secret"])


def _access_token() -> str:
    client_id, client_secret = _client()
    data = urlencode({"client_id": client_id, "client_secret": client_secret, "refresh_token": get_gmail_refresh_token(), "grant_type": "refresh_token"}).encode()
    with urlopen(Request(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=25) as response:
        return str(json.loads(response.read().decode())["access_token"])


def send(message: EmailMessage) -> str:
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
    request = Request(SEND_URL, data=json.dumps({"raw": raw}).encode(), method="POST", headers={"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return str(json.loads(response.read().decode()).get("id", "sent"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail[:300]) from exc
    except (URLError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)) from exc
