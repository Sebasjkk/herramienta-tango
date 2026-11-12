"""
Token de Tango guardado cifrado con DPAPI de Windows.

token.dat solo lo puede descifrar el mismo usuario de Windows en la misma PC.
Fuera de Windows (solo para pruebas) se guarda sin cifrar con permisos 600.
"""

from __future__ import annotations

import getpass
import logging
import os

from .config import RUTA_TOKEN

log = logging.getLogger("herramienta_tango")
LARGO_TOKEN = 36


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


def _guardar(token: str) -> None:
    datos = token.encode("utf-8")
    if os.name == "nt":
        RUTA_TOKEN.write_bytes(_dpapi(datos, cifrar=True))
    else:
        RUTA_TOKEN.write_bytes(datos)
        os.chmod(RUTA_TOKEN, 0o600)


def _leer() -> str | None:
    if not RUTA_TOKEN.exists():
        return None
    try:
        datos = RUTA_TOKEN.read_bytes()
        if os.name == "nt":
            datos = _dpapi(datos, cifrar=False)
        return datos.decode("utf-8").strip()
    except Exception:
        log.warning("No se pudo leer token.dat (se guardó con otro usuario o en otra PC).")
        return None


def _pedir() -> str:
    print()
    print("Hace falta el token de desarrollador de Tango.")
    print("Se genera en el Tango web: menú de usuario > Desarrollador > Generar > Aceptar.")
    while True:
        token = getpass.getpass("Pegá el token (no se muestra al escribir) y apretá Enter: ").strip()
        if len(token) == LARGO_TOKEN and token.count("-") == 4:
            return token
        print(f"  Ese token tiene {len(token)} caracteres; debería tener {LARGO_TOKEN} "
              "(formato XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX). Probá de nuevo.")


def obtener_token(forzar_nuevo: bool = False) -> str:
    if os.environ.get("HERRAMIENTA_TANGO_TOKEN"):  # solo para pruebas
        return os.environ["HERRAMIENTA_TANGO_TOKEN"].strip()
    if not forzar_nuevo:
        token = _leer()
        if token:
            return token
    token = _pedir()
    _guardar(token)
    log.info("Token guardado cifrado en token.dat")
    return token
