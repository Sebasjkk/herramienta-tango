"""
Integracion con Windows: instalacion, inicio automatico, accesos directos, avisos y red.

El programa corre con el Python oficial (pythonw.exe, firmado por la Python
Software Foundation) y su codigo son archivos .py. No hay un .exe propio, para
que los antivirus no lo confundan con algo peligroso.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import config

CLAVE_INICIO = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOMBRE_INICIO = "HerramientaTango"
NOMBRE_ACCESO = "Herramienta Tango"
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def es_windows() -> bool:
    return os.name == "nt"


@dataclass(frozen=True)
class Instalacion:
    raiz: Path
    pythonw: Path
    script: Path
    icono: Path

    @property
    def comando(self) -> list[str]:
        return [str(self.pythonw), str(self.script)]


def instalacion() -> Instalacion | None:
    """Datos de la instalacion, o None si corre desde el codigo fuente."""
    raiz = config.CARPETA
    pythonw = raiz / "python" / "pythonw.exe"
    script = raiz / "app" / "HerramientaTango.pyw"
    if config.CARPETA_CODIGO.name != "app" or not pythonw.exists() or not script.exists():
        return None
    return Instalacion(raiz, pythonw, script, raiz / "app" / "recursos" / "icono.ico")


# ------------------------------------------------------------ inicio con Windows
def inicio_automatico_activo() -> bool:
    inst = instalacion()
    if not es_windows() or not inst:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_INICIO) as k:
            valor, _ = winreg.QueryValueEx(k, NOMBRE_INICIO)
            return str(inst.script).lower() in str(valor).lower()
    except OSError:
        return False


def activar_inicio_automatico(activo: bool) -> None:
    """Agrega o saca el programa del inicio de Windows (solo para el usuario actual)."""
    inst = instalacion()
    if not es_windows() or (activo and not inst):
        raise OSError("Solo disponible con el programa instalado en Windows.")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_INICIO, 0, winreg.KEY_SET_VALUE) as k:
        if activo:
            winreg.SetValueEx(k, NOMBRE_INICIO, 0, winreg.REG_SZ,
                              f'"{inst.pythonw}" "{inst.script}" --no-abrir')
        else:
            try:
                winreg.DeleteValue(k, NOMBRE_INICIO)
            except FileNotFoundError:
                pass


# ------------------------------------------------------------ accesos directos
def crear_accesos_directos() -> list[str]:
    """Crea 'Herramienta Tango' en el escritorio y en el menu Inicio. Devuelve donde los creo."""
    inst = instalacion()
    if not es_windows() or not inst:
        return []

    def ps(texto: str) -> str:
        return texto.replace("'", "''")

    script = f"""
$ws = New-Object -ComObject WScript.Shell
$destinos = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
foreach ($d in $destinos) {{
  if (-not $d) {{ continue }}
  $s = $ws.CreateShortcut((Join-Path $d '{ps(NOMBRE_ACCESO)}.lnk'))
  $s.TargetPath = '{ps(str(inst.pythonw))}'
  $s.Arguments = '"{ps(str(inst.script))}"'
  $s.WorkingDirectory = '{ps(str(inst.raiz))}'
  $s.IconLocation = '{ps(str(inst.icono))}'
  $s.Description = 'Herramienta Tango: panel y consultas sobre Tango'
  $s.Save()
  Write-Output $d
}}
"""
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                       capture_output=True, text=True, timeout=60, creationflags=SIN_VENTANA)
    if r.returncode != 0:
        raise OSError(r.stderr.strip() or "No se pudieron crear los accesos directos")
    return [l for l in r.stdout.splitlines() if l.strip()]


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
