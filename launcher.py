"""
launcher.py — Rastreador OSINT-BOOLEANO v1.3.8
Inicio del sistema: muestra la clave de acceso movil y luego inicia el servidor.

COMPILAR CON:
    pip install pyinstaller
    pyinstaller --onefile --console --name "OSINT-BOOLEANO" launcher.py

El .exe resultante va en la misma carpeta que las subcarpetas config/, data/, alerts/.
"""
import sys
import os
import json
import ctypes
import subprocess
from pathlib import Path


API_CREDENTIAL_TARGET = "RastreadorOSINTBooleanoAPI"


def get_api_token() -> str:
    """Lee el token de acceso movil desde Windows Credential Manager."""
    if sys.platform != "win32":
        return os.getenv("BRIDGE_API_TOKEN", "")
    try:
        from ctypes import wintypes

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        pointer = ctypes.POINTER(CREDENTIALW)()
        advapi32 = ctypes.WinDLL("Advapi32.dll")
        if not advapi32.CredReadW(API_CREDENTIAL_TARGET, 1, 0, ctypes.byref(pointer)):
            return os.getenv("BRIDGE_API_TOKEN", "")
        try:
            credential = pointer.contents
            raw = ctypes.string_at(
                credential.CredentialBlob, credential.CredentialBlobSize
            )
            return raw.decode("utf-16-le")
        finally:
            advapi32.CredFree(pointer)
    except (OSError, ValueError, AttributeError):
        return os.getenv("BRIDGE_API_TOKEN", "")


def mostrar_clave_en_txt(token: str, base_dir: Path) -> None:
    """Escribe la clave en CLAVE_ACCESO.txt y lo abre con el Bloc de notas."""
    if token:
        contenido = (
            "============================================================\n"
            "  RASTREADOR OSINT-BOOLEANO v1.3.8\n"
            "  CLAVE DE ACCESO MOVIL\n"
            "============================================================\n\n"
            f"  CLAVE: {token}\n\n"
            "------------------------------------------------------------\n"
            "  COMO USAR:\n"
            "  1. Abra el panel en su telefono o tablet:\n"
            "     http://[IP-DEL-SERVIDOR]:8765/mobile\n\n"
            "  2. Ingrese esta clave cuando el panel la solicite.\n\n"
            "  3. Guarde esta clave en un lugar seguro.\n"
            "     No la comparta con personas no autorizadas.\n"
            "============================================================\n"
        )
    else:
        contenido = (
            "============================================================\n"
            "  RASTREADOR OSINT-BOOLEANO v1.3.8\n"
            "  SIN CLAVE CONFIGURADA\n"
            "============================================================\n\n"
            "  El sistema funciona en modo LOCAL unicamente.\n"
            "  Para habilitar acceso movil, ejecute:\n\n"
            "    cmdkey /generic:RastreadorOSINTBooleanoAPI\n"
            "           /user:bridge /pass:SU_CLAVE_AQUI\n\n"
            "  O ejecute configure_email.ps1 y siga las instrucciones.\n"
            "============================================================\n"
        )

    clave_file = base_dir / "CLAVE_ACCESO.txt"
    try:
        clave_file.write_text(contenido, encoding="utf-8")
        subprocess.Popen(["notepad.exe", str(clave_file)])
    except Exception as e:
        print(f"[AVISO] No se pudo mostrar archivo de clave: {e}")


def iniciar_servidor(app_root: Path) -> None:
    """Inicia el servidor bridge con las rutas correctas al directorio de la app."""
    config_dir = app_root / "config"
    data_dir = app_root / "data"
    alerts_dir = app_root / "alerts"
    reports_dir = app_root / "reports"

    # Crear directorios de datos si no existen
    data_dir.mkdir(exist_ok=True)
    alerts_dir.mkdir(exist_ok=True)
    reports_dir.mkdir(exist_ok=True)

    # Agregar la raiz de la app al path para que "import bridge" funcione
    sys.path.insert(0, str(app_root))

    argv = [
        "--config", str(config_dir / "sources.json"),
        "--aliases", str(config_dir / "aliases.json"),
        "--database", str(data_dir / "bridge.sqlite3"),
        "--watches", str(config_dir / "watch_queries.json"),
        "--alerts-dir", str(alerts_dir),
        "--reports-dir", str(reports_dir),
    ]
    source_config = json.loads((config_dir / "sources.json").read_text(encoding="utf-8"))
    ai_settings = source_config.get("ai", {})
    from bridge.ai import _api_key
    ai_status = "Claude Haiku habilitado" if ai_settings.get("enabled") and _api_key() else "Claude Haiku sin clave"

    print("=" * 60)
    print("  RASTREADOR OSINT-BOOLEANO v1.3.8")
    print("  Iniciando servidor en http://127.0.0.1:8765")
    print("  Panel local: http://127.0.0.1:8765/mobile")
    print(f"  IA: {ai_status}")
    print("=" * 60)

    from bridge.server import main as server_main
    sys.exit(server_main(argv))


def main() -> None:
    # Determinar el directorio raiz de la aplicacion
    if getattr(sys, "frozen", False):
        # Corriendo como .exe compilado con PyInstaller
        app_root = Path(sys.executable).parent
    else:
        # Corriendo como script Python normal
        app_root = Path(__file__).resolve().parent

    # 1. Leer la clave de acceso
    token = get_api_token()

    # 2. Mostrar la clave en un archivo de texto
    mostrar_clave_en_txt(token, app_root)

    # 3. Iniciar el servidor (bloqueante hasta que se cierre)
    iniciar_servidor(app_root)


if __name__ == "__main__":
    main()
