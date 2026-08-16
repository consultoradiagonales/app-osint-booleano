"""Instalador autónomo de Rastreador OSINT-BOOLEANO para Windows."""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "Rastreador OSINT-BOOLEANO"


def bundle_path(relative: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / relative


def desktop_dir() -> Path:
    path = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, path) == 0:
        return Path(path.value)
    return Path.home() / "Desktop"


def copy_payload(source: Path, destination: Path) -> None:
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def main() -> int:
    readme = bundle_path("README_INSTALACION.txt")
    subprocess.Popen(["notepad.exe", str(readme)])
    print(f"\n{APP_NAME}\n")
    input("Lea el README y presione ENTER para instalar. ")

    target = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Consultora Diagonales" / "OSINT-BOOLEANO"
    target.mkdir(parents=True, exist_ok=True)
    copy_payload(bundle_path("payload/app"), target)
    config_source = bundle_path("payload/config")
    config_target = target / "config"
    config_target.mkdir(exist_ok=True)
    for item in config_source.iterdir():
        destination = config_target / item.name
        if not destination.exists():
            shutil.copy2(item, destination)
    for name in ("data", "alerts", "reports"):
        (target / name).mkdir(exist_ok=True)
    shutil.copy2(readme, target / "README_INSTALACION.txt")

    panel_url = "http://127.0.0.1:8765/mobile"
    shortcut = desktop_dir() / "OSINT-BOOLEANO.html"
    shortcut.write_text(
        "<!doctype html><meta charset='utf-8'><meta http-equiv='refresh' content='0;url=" + panel_url + "'>"
        "<title>Rastreador OSINT-BOOLEANO</title><p>Abriendo <a href='" + panel_url + "'>Rastreador OSINT-BOOLEANO</a>…</p>",
        encoding="utf-8",
    )
    task = "Consultora Diagonales - OSINT BOOLEANO"
    subprocess.run([
        "schtasks", "/Create", "/F", "/SC", "HOURLY", "/MO", "1", "/TN", task,
        "/TR", str(target / "OSINT-BOOLEANO-Rastreo.exe"),
    ], capture_output=True, text=True, check=False)
    subprocess.Popen([str(target / "OSINT-BOOLEANO.exe")], cwd=target)
    print(f"\nInstalación completada en: {target}")
    print(f"Acceso directo creado: {shortcut}")
    print("El panel se abrirá en unos segundos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
