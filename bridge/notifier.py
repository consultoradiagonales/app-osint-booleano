from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import html
import os
from pathlib import Path
import re
import smtplib
import subprocess
import sys
from typing import Iterable
import uuid

from . import gmail_delivery
from .windows_credentials import get_smtp_password


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


def email_status() -> dict[str, object]:
    host = _setting("OSINT_SMTP_HOST").strip()
    user = _setting("OSINT_SMTP_USER").strip()
    sender = _setting("OSINT_SMTP_FROM", user).strip()
    password = get_smtp_password()
    return {
        "configured": bool(host and sender and password),
        "host": host,
        "sender": sender,
        "password_stored": bool(password),
    }


def _html_body(body: str) -> str:
    rendered: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"https?://\S+", stripped):
            safe_url = html.escape(stripped, quote=True)
            rendered.append(f'<a href="{safe_url}">{html.escape(stripped)}</a>')
        else:
            rendered.append(html.escape(line))
    return "<br>".join(rendered)


def create_calendar_invite(subject: str, body: str, recipient: str, sender: str) -> str:
    now = datetime.now(timezone.utc)
    start = now + timedelta(minutes=2)
    end = start + timedelta(minutes=15)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    first_url = next(iter(re.findall(r"https?://\S+", body)), "")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Consultora Diagonales//Rastreador OSINT-BOOLEANO 1.3.8//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4().hex}@rastreador-osint-booleano.local",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{_ics_escape(subject)}",
        f"DESCRIPTION:{_ics_escape(body)}",
        f"ORGANIZER:mailto:{sender}",
        f"ATTENDEE;CN={_ics_escape(recipient)};RSVP=FALSE:mailto:{recipient}",
        "STATUS:CONFIRMED",
        "SEQUENCE:0",
        "TRANSP:TRANSPARENT",
    ]
    if first_url:
        lines.append(f"URL:{first_url}")
    lines.extend(
        [
            "BEGIN:VALARM",
            "TRIGGER:-PT0M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_ics_escape(subject)}",
            "END:VALARM",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    return "\r\n".join(lines)



def _gcal_url(subject: str, body: str) -> str:
    """URL para agregar evento a Google Calendar con un click."""
    from urllib.parse import urlencode
    now = datetime.now(timezone.utc)
    start = now + timedelta(minutes=2)
    end = start + timedelta(minutes=15)
    fmt = "%Y%m%dT%H%M%SZ"
    clean = re.sub(r"https?://\S+", "", body)[:400].strip()
    return "https://calendar.google.com/calendar/render?" + urlencode({
        "action": "TEMPLATE",
        "text": subject[:100],
        "dates": f"{start.strftime(fmt)}/{end.strftime(fmt)}",
        "details": clean,
    })


def build_email_message(sender: str, recipient: str, subject: str, body: str, html_body: str = "") -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body + "\n\nAlerta automática del Rastreador OSINT–BOOLEANO.")
    if html_body:
        message.add_alternative(html_body, subtype="html")
        return message
    message.add_alternative(
        '<div style="font-family:Arial,sans-serif;line-height:1.5">'
        + _html_body(body)
        + "<br><br><small>Alerta automática del Rastreador OSINT–BOOLEANO.</small></div>",
        subtype="html",
    )
    return message


def send_email_alert(recipients: Iterable[str], subject: str, body: str, html_body: str = "") -> list[dict[str, str]]:
    addresses = list(dict.fromkeys(recipients))
    if not addresses:
        return []
    if gmail_delivery.configured():
        sender = _setting("OSINT_GMAIL_FROM", "info.consultoradiagonales@gmail.com").strip()
        results: list[dict[str, str]] = []
        for email in addresses:
            try:
                gmail_delivery.send(build_email_message(sender, email, subject, body, html_body))
                results.append({"email": email, "status": "sent", "error": ""})
            except RuntimeError as exc:
                results.append({"email": email, "status": "failed", "error": str(exc)})
        return results
    status = email_status()
    if not status["configured"]:
        return [{"email": email, "status": "skipped", "error": "SMTP no configurado"} for email in addresses]
    host = str(status["host"])
    port = int(_setting("OSINT_SMTP_PORT", "587"))
    user = _setting("OSINT_SMTP_USER").strip()
    password = get_smtp_password()
    use_ssl = _setting("OSINT_SMTP_SSL", "false").lower() in {"1", "true", "yes", "si"}
    use_starttls = _setting("OSINT_SMTP_STARTTLS", "true").lower() in {"1", "true", "yes", "si"}
    results: list[dict[str, str]] = []
    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    try:
        with smtp_class(host, port, timeout=25) as client:
            if not use_ssl and use_starttls:
                client.starttls()
            if user:
                client.login(user, password)
            for email in addresses:
                message = build_email_message(str(status["sender"]), email, subject, body, html_body)
                try:
                    client.send_message(message)
                    results.append({"email": email, "status": "sent", "error": ""})
                except (smtplib.SMTPException, OSError) as exc:
                    results.append({"email": email, "status": "failed", "error": str(exc)})
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        return [{"email": email, "status": "failed", "error": str(exc)} for email in addresses]
    return results


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def create_ics(alerts_dir: str | Path, watch_id: str, title: str, body: str) -> Path:
    directory = Path(alerts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    start = now + timedelta(minutes=2)
    end = start + timedelta(minutes=15)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    uid = f"{watch_id}-{stamp}@rastreador-osint-booleano.local"
    payload = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Consultora Diagonales//Rastreador OSINT-BOOLEANO 1.3.8//ES",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{_ics_escape(title)}",
            f"DESCRIPTION:{_ics_escape(body)}",
            "BEGIN:VALARM",
            "TRIGGER:-PT0M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_ics_escape(title)}",
            "END:VALARM",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    path = directory / f"{watch_id}_{now.strftime('%Y%m%d_%H%M%S')}.ics"
    path.write_text(payload, encoding="utf-8", newline="")
    return path


def _powershell(script: str, environment: dict[str, str]) -> bool:
    if sys.platform != "win32":
        return False
    env = os.environ.copy()
    env.update(environment)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=flags,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _powershell_detached(script: str, environment: dict[str, str]) -> bool:
    """Launch a user notification without blocking the watcher until it is dismissed."""
    if sys.platform != "win32":
        return False
    env = os.environ.copy()
    env.update(environment)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        return True
    except OSError:
        return False


def create_outlook_calendar_event(title: str, body: str) -> bool:
    script = """
$outlook = New-Object -ComObject Outlook.Application
$event = $outlook.CreateItem(1)
$event.Subject = $env:OSINT_ALERT_TITLE
$event.Body = $env:OSINT_ALERT_BODY
$event.Start = (Get-Date).AddMinutes(2)
$event.Duration = 15
$event.ReminderSet = $true
$event.ReminderMinutesBeforeStart = 0
$event.BusyStatus = 0
$event.Save()
"""
    return _powershell(script, {"OSINT_ALERT_TITLE": title, "OSINT_ALERT_BODY": body})


def show_windows_alert(title: str, body: str) -> bool:
    short_body = body[:1800]
    script = """
$shell = New-Object -ComObject WScript.Shell
$null = $shell.Popup($env:OSINT_ALERT_BODY, 45, $env:OSINT_ALERT_TITLE, 64)
"""
    return _powershell_detached(script, {"OSINT_ALERT_TITLE": title, "OSINT_ALERT_BODY": short_body})


def send_alert(alerts_dir: str | Path, watch_id: str, title: str, body: str) -> dict[str, object]:
    ics_path = create_ics(alerts_dir, watch_id, title, body)
    outlook_created = create_outlook_calendar_event(title, body)
    first_line = body.splitlines()[0] if body else "Se detectaron nuevos hallazgos."
    popup_sent = show_windows_alert(
        title,
        first_line + "\n\nAbrí el panel o revisá el correo para acceder a los enlaces.",
    )
    return {
        "outlook_calendar_created": outlook_created,
        "windows_popup_sent": popup_sent,
        "ics_path": str(ics_path),
        "google_calendar_compatible": True,
        "ai_used": False,
        "paid_services_used": False,
    }
