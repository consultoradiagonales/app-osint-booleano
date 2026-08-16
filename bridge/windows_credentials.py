from __future__ import annotations

import os
import sys


CREDENTIAL_TARGET = "RastreadorOSINTBooleanoSMTP"
API_CREDENTIAL_TARGET = "RastreadorOSINTBooleanoAPI"
GOOGLE_CALENDAR_CREDENTIAL_TARGET = "RastreadorOSINTBooleanoGoogleCalendar"
GMAIL_CREDENTIAL_TARGET = "RastreadorOSINTBooleanoGmail"


def _read_windows_credential(target: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
            ]

        pointer = ctypes.POINTER(CREDENTIALW)()
        advapi32 = ctypes.WinDLL("Advapi32.dll")
        if not advapi32.CredReadW(target, 1, 0, ctypes.byref(pointer)):
            return ""
        try:
            credential = pointer.contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return raw.decode("utf-16-le")
        finally:
            advapi32.CredFree(pointer)
    except (OSError, ValueError, AttributeError):
        return ""


def get_smtp_password() -> str:
    """Read the SMTP secret from Windows Credential Manager, with an env fallback."""
    return _read_windows_credential(CREDENTIAL_TARGET) or os.getenv("OSINT_SMTP_PASSWORD", "")


def get_api_token() -> str:
    """Read the mobile API token without keeping it in project configuration files."""
    return _read_windows_credential(API_CREDENTIAL_TARGET) or os.getenv("BRIDGE_API_TOKEN", "")


def get_google_calendar_refresh_token() -> str:
    """Read the OAuth refresh token used only by the local Calendar publisher."""
    return _read_windows_credential(GOOGLE_CALENDAR_CREDENTIAL_TARGET) or os.getenv("OSINT_GCAL_REFRESH_TOKEN", "")


def get_gmail_refresh_token() -> str:
    """OAuth token for sending from the Consultora mailbox without SMTP passwords."""
    return _read_windows_credential(GMAIL_CREDENTIAL_TARGET) or os.getenv("OSINT_GMAIL_REFRESH_TOKEN", "")
