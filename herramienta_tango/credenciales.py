"""
Token de Tango guardado cifrado con DPAPI de Windows.

token.dat solo lo puede descifrar el mismo usuario de Windows en la misma PC.
Fuera de Windows (solo para pruebas) se guarda sin cifrar con permisos 600.
"""

from __future__ import annotations

import logging
import os
import re

from . import config

log = logging.getLogger("herramienta_tango")

PATRON_TOKEN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def formato_valido(token: str) -> bool:
    return bool(PATRON_TOKEN.match((token or "").strip()))


def _dpapi(datos: bytes, cifrar: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(datos, len(datos))
    entrada = DATA_BLOB(len(datos), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    salida = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    funcion = crypt32.CryptProtectData if cifrar else crypt32.CryptUnprotectData
    if not funcion(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida)):
        raise OSError("DPAPI no pudo procesar el token")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def guardar_token(token: str) -> None:
    datos = token.strip().encode("utf-8")
    if os.name == "nt":
        config.RUTA_TOKEN.write_bytes(_dpapi(datos, cifrar=True))
    else:
        config.RUTA_TOKEN.write_bytes(datos)
        os.chmod(config.RUTA_TOKEN, 0o600)


def leer_token() -> str | None:
    if os.environ.get("HERRAMIENTA_TANGO_TOKEN"):  # solo para pruebas
        return os.environ["HERRAMIENTA_TANGO_TOKEN"].strip()
    if not config.RUTA_TOKEN.exists():
        return None
    try:
        datos = config.RUTA_TOKEN.read_bytes()
        if os.name == "nt":
            datos = _dpapi(datos, cifrar=False)
        token = datos.decode("utf-8").strip()
        return token or None
    except Exception:
        log.warning("No se pudo leer token.dat (se guardó con otro usuario o en otra PC).")
        return None
