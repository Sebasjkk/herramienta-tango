"""Integracion con Windows: inicio automatico, avisos y red."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

CLAVE_INICIO = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOMBRE_INICIO = "HerramientaTango"


def es_windows() -> bool:
    return os.name == "nt"


def ruta_exe() -> Path | None:
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


# ------------------------------------------------------------ inicio con Windows
def inicio_automatico_activo() -> bool:
    if not es_windows():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_INICIO) as k:
            valor, _ = winreg.QueryValueEx(k, NOMBRE_INICIO)
            exe = ruta_exe()
            return bool(exe) and str(exe).lower() in str(valor).lower()
    except OSError:
        return False


def activar_inicio_automatico(activo: bool) -> None:
    """Agrega o saca el programa del inicio de Windows (solo para el usuario actual)."""
    if not es_windows():
        raise OSError("Solo disponible en Windows.")
    exe = ruta_exe()
    if activo and not exe:
        raise OSError("Solo disponible en el .exe.")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_INICIO, 0, winreg.KEY_SET_VALUE) as k:
        if activo:
            winreg.SetValueEx(k, NOMBRE_INICIO, 0, winreg.REG_SZ, f'"{exe}" --no-abrir')
        else:
            try:
                winreg.DeleteValue(k, NOMBRE_INICIO)
            except FileNotFoundError:
                pass


# ------------------------------------------------------------ avisos
def aviso(titulo: str, mensaje: str, error: bool = True) -> None:
    """Ventana de aviso de Windows (el programa no tiene consola)."""
    if es_windows():
        import ctypes
        icono = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, mensaje, titulo, icono | 0x40000)  # MB_TOPMOST
    else:
        print(f"{titulo}: {mensaje}", file=sys.stderr)


# ------------------------------------------------------------ red
def direcciones_locales() -> list[str]:
    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no envia nada; solo elige la interfaz de red
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips.update(ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith("127."))
    except OSError:
        pass
    # Primero las de red local tipica
    return sorted(ips, key=lambda ip: (not ip.startswith(("192.168.", "10.", "172.")), ip))
