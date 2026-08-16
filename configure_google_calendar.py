from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import webbrowser


ROOT = Path(__file__).resolve().parent
CLIENT_PATH = Path(r"C:\Users\FAMILIA\Desktop\ESCANEOS\client_secret.json.json")
TARGET = "RastreadorOSINTBooleanoGoogleCalendar"
ORGANIZER = "info.consultoradiagonales@gmail.com"
CALENDAR_NAME = "CABLE DE NOTICIAS CONSULTORA DIAGONALES"
SCOPES = "openid email https://www.googleapis.com/auth/calendar"


def post_form(url: str, values: dict[str, str]) -> dict:
    request = Request(
        url,
        data=urlencode(values).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def api(url: str, token: str, method: str = "GET", data: dict | None = None) -> dict:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def set_user_environment(name: str, value: str) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def main() -> int:
    if not CLIENT_PATH.is_file():
        raise RuntimeError(f"No se encontró la configuración OAuth: {CLIENT_PATH}")
    payload = json.loads(CLIENT_PATH.read_text(encoding="utf-8"))
    client = payload.get("installed") or payload.get("web") or {}
    client_id = client["client_id"]
    client_secret = client["client_secret"]
    state = secrets.token_urlsafe(32)
    answer: dict[str, str] = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            answer["state"] = query.get("state", [""])[0]
            answer["code"] = query.get("code", [""])[0]
            answer["error"] = query.get("error", [""])[0]
            message = (
                "Google Calendar quedó autorizado. Puede cerrar esta ventana."
                if answer["code"]
                else "No se completó la autorización. Puede cerrar esta ventana."
            )
            body = f"<!doctype html><meta charset='utf-8'><title>OSINT-BOOLEANO</title><h2>{message}</h2>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args) -> None:
            pass

    server = HTTPServer(("localhost", 0), Callback)
    server.timeout = 300
    redirect_uri = f"http://localhost:{server.server_port}/"
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "login_hint": ORGANIZER,
            "state": state,
        }
    )
    print("Autorice la cuenta info.consultoradiagonales@gmail.com en el navegador.")
    (ROOT / "data" / "google-calendar-auth-url.txt").write_text(authorization_url, encoding="utf-8")
    chrome_paths = (
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    )
    chrome = next((path for path in chrome_paths if path.is_file()), None)
    if chrome:
        subprocess.Popen([str(chrome), "--new-window", authorization_url])
    else:
        webbrowser.open(authorization_url, new=1, autoraise=True)
    server.handle_request()
    server.server_close()
    if answer.get("state") != state or not answer.get("code"):
        raise RuntimeError(answer.get("error") or "La autorización no se completó")

    tokens = post_form(
        "https://oauth2.googleapis.com/token",
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": answer["code"],
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        raise RuntimeError("Google no devolvió una autorización permanente")
    profile = api("https://www.googleapis.com/oauth2/v2/userinfo", access_token)
    if str(profile.get("email", "")).lower() != ORGANIZER:
        raise RuntimeError(f"Se autorizó {profile.get('email', 'otra cuenta')}; debe usar {ORGANIZER}")

    calendars = api("https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=250", access_token)
    selected = next((item for item in calendars.get("items", []) if item.get("summary") == CALENDAR_NAME), None)
    if selected is None:
        selected = api(
            "https://www.googleapis.com/calendar/v3/calendars",
            access_token,
            "POST",
            {
                "summary": CALENDAR_NAME,
                "description": "Alertas OSINT–BOOLEANO de Consultora Diagonales. Sin envío de correos por cada cable.",
                "timeZone": "America/Argentina/Buenos_Aires",
            },
        )
    calendar_id = selected["id"]
    result = subprocess.run(
        ["cmdkey.exe", f"/generic:{TARGET}", f"/user:{ORGANIZER}", f"/pass:{refresh_token}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Windows no pudo guardar la autorización de Calendar")

    settings = {
        "OSINT_GCAL_CLIENT_SECRET_PATH": str(CLIENT_PATH),
        "OSINT_GCAL_CALENDAR_ID": str(calendar_id),
        "OSINT_GCAL_CALENDAR_NAME": CALENDAR_NAME,
        "OSINT_GCAL_ORGANIZER": ORGANIZER,
        "OSINT_ALERT_DELIVERY_MODE": "calendar_only",
        "OSINT_SMTP_USER": ORGANIZER,
        "OSINT_SMTP_FROM": ORGANIZER,
    }
    for name, value in settings.items():
        set_user_environment(name, value)
        os.environ[name] = value

    sys.path.insert(0, str(ROOT))
    from bridge.google_calendar import sync_calendar_subscribers
    from bridge.recipients import RecipientStore

    recipients = [item["email"] for item in RecipientStore(ROOT / "data" / "bridge.sqlite3").list(enabled_only=True)]
    subscriptions = sync_calendar_subscribers(recipients)
    (ROOT / "data" / "google-calendar-setup.log").write_text(
        json.dumps(
            {
                "ok": True,
                "organizer": ORGANIZER,
                "calendar_name": CALENDAR_NAME,
                "subscribers": subscriptions,
                "email_alerts": False,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    subprocess.run(["cmd.exe", "/c", str(ROOT / "restart_bridge.bat")], cwd=ROOT, check=False)
    print("Google Calendar configurado. Las alertas por correo quedaron desactivadas.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, HTTPError, URLError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        (ROOT / "data").mkdir(parents=True, exist_ok=True)
        (ROOT / "data" / "google-calendar-setup.log").write_text(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"ERROR: {exc}")
        raise SystemExit(2)
