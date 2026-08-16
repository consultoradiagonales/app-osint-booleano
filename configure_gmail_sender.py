"""Autoriza el envío Gmail de Consultora Diagonales sin contraseña SMTP."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent
ORGANIZER = "info.consultoradiagonales@gmail.com"
TARGET = "RastreadorOSINTBooleanoGmail"
SCOPES = "openid email https://www.googleapis.com/auth/gmail.send"


def post_form(values: dict[str, str]) -> dict:
    request = Request("https://oauth2.googleapis.com/token", data=urlencode(values).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def set_user_environment(name: str, value: str) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def main() -> int:
    client_path = Path(os.getenv("OSINT_GCAL_CLIENT_SECRET_PATH", r"C:\Users\FAMILIA\Desktop\ESCANEOS\client_secret.json.json"))
    if not client_path.is_file():
        raise RuntimeError("No se encontró la configuración OAuth de Google en esta PC")
    client = (json.loads(client_path.read_text(encoding="utf-8")).get("installed") or json.loads(client_path.read_text(encoding="utf-8")).get("web") or {})
    state, answer = secrets.token_urlsafe(32), {}
    class Callback(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = parse_qs(urlparse(self.path).query)
            answer.update({key: query.get(key, [""])[0] for key in ("state", "code", "error")})
            body = b"<meta charset='utf-8'><h2>Correo de Consultora Diagonales autorizado. Puede cerrar esta ventana.</h2>"
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, _format: str, *_args) -> None: pass
    server = HTTPServer(("localhost", 0), Callback); server.timeout = 300
    redirect_uri = f"http://localhost:{server.server_port}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({"client_id": client["client_id"], "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPES, "access_type": "offline", "prompt": "consent", "login_hint": ORGANIZER, "state": state})
    (ROOT / "data" / "gmail-sender-auth-url.txt").write_text(url, encoding="utf-8")
    webbrowser.open(url, new=1)
    server.handle_request(); server.server_close()
    if answer.get("state") != state or not answer.get("code"): raise RuntimeError(answer.get("error") or "No se completó la autorización")
    tokens = post_form({"client_id": client["client_id"], "client_secret": client["client_secret"], "code": answer["code"], "grant_type": "authorization_code", "redirect_uri": redirect_uri})
    refresh_token = str(tokens.get("refresh_token", ""))
    if not refresh_token: raise RuntimeError("Google no entregó autorización permanente")
    subprocess.run(["cmdkey.exe", f"/generic:{TARGET}", f"/user:{ORGANIZER}", f"/pass:{refresh_token}"], check=True)
    for name, value in {"OSINT_GMAIL_ENABLED":"true", "OSINT_GMAIL_CLIENT_SECRET_PATH":str(client_path), "OSINT_GMAIL_FROM":ORGANIZER, "OSINT_SMTP_USER":ORGANIZER, "OSINT_SMTP_FROM":ORGANIZER}.items(): set_user_environment(name, value)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
