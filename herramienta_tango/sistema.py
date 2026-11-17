"""
Integracion con Windows: instalacion, inicio automatico, modo servidor,
accesos directos, avisos y red.

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
NOMBRE_TAREA = "Herramienta Tango"      # tarea programada y regla del firewall del modo servidor
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Corriendo como servicio (sin nadie frente a la pantalla): no se muestran ventanas de aviso
SIN_AVISOS = False

# Redes privadas desde donde se acepta entrar en modo servidor (Wi-Fi y cableada de la oficina)
REDES_PRIVADAS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")


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


# ------------------------------------------------------------ modo servidor
# El programa corre como tarea programada de Windows con la cuenta SYSTEM: arranca
# al prender la PC aunque nadie inicie sesion, y el firewall deja entrar a las
# otras PCs y celulares de la red privada. Crear la tarea y la regla necesita
# permiso de administrador (una ventana de Windows lo pide una vez).
def marca_modo_servidor() -> Path:
    return config.CARPETA / "modo_servidor.txt"


def modo_servidor_activo() -> bool:
    return marca_modo_servidor().exists()


def _ps(texto: str) -> str:
    return texto.replace("'", "''")


def script_activar_servidor(inst: Instalacion, puerto: int, pid_a_esperar: int | None) -> str:
    """PowerShell (como administrador) que crea la tarea y la regla del firewall y arranca la tarea."""
    redes = ",".join(f"'{r}'" for r in REDES_PRIVADAS)
    esperar = f"Wait-Process -Id {pid_a_esperar} -Timeout 60 -ErrorAction SilentlyContinue" if pid_a_esperar else ""
    return f"""
$ErrorActionPreference = 'Stop'
$marca = '{_ps(str(marca_modo_servidor()))}'
$error_archivo = '{_ps(str(config.CARPETA / "modo_servidor_error.txt"))}'
try {{
  $accion = New-ScheduledTaskAction -Execute '{_ps(str(inst.pythonw))}' -Argument '"{_ps(str(inst.script))}" --servicio' -WorkingDirectory '{_ps(str(inst.raiz))}'
  $disparador = New-ScheduledTaskTrigger -AtStartup
  $cuenta = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
  $ajustes = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName '{_ps(NOMBRE_TAREA)}' -Action $accion -Trigger $disparador -Principal $cuenta -Settings $ajustes -Description 'Herramienta Tango: consultas sobre Tango para las PCs y celulares de la oficina' -Force | Out-Null
  Get-NetFirewallRule -DisplayName '{_ps(NOMBRE_TAREA)}' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
  New-NetFirewallRule -DisplayName '{_ps(NOMBRE_TAREA)}' -Direction Inbound -Action Allow -Protocol TCP -LocalPort {int(puerto)} -RemoteAddress {redes} -Profile Any | Out-Null
  Set-Content -Path $marca -Value 'Herramienta Tango corre como tarea programada de Windows (modo servidor).' -Encoding UTF8
  {esperar}
  Start-ScheduledTask -TaskName '{_ps(NOMBRE_TAREA)}'
}} catch {{
  Set-Content -Path $error_archivo -Value $_.Exception.Message -Encoding UTF8
}}
"""


def script_desactivar_servidor() -> str:
    return f"""
$ErrorActionPreference = 'SilentlyContinue'
Remove-Item -Path '{_ps(str(marca_modo_servidor()))}' -Force
Get-NetFirewallRule -DisplayName '{_ps(NOMBRE_TAREA)}' | Remove-NetFirewallRule
# Al final: borrar la tarea puede cortar este mismo script si corre dentro de ella
Unregister-ScheduledTask -TaskName '{_ps(NOMBRE_TAREA)}' -Confirm:$false
"""


def ejecutar_powershell(script: str, como_admin: bool) -> None:
    """Corre un script de PowerShell sin ventana. Con como_admin, Windows pide permiso;
    si el usuario dice que no, lanza OSError. No espera a que el script termine."""
    if not es_windows():
        raise OSError("Solo disponible en Windows.")
    if not como_admin:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, text=True, timeout=120, creationflags=SIN_VENTANA)
        if r.returncode != 0:
            raise OSError(r.stderr.strip() or "PowerShell devolvió un error")
        return
    archivo = config.CARPETA / "modo_servidor.ps1"
    archivo.write_text(script, encoding="utf-8-sig")
    lanzar = (f"Start-Process powershell -Verb RunAs -WindowStyle Hidden -ArgumentList "
              f"'-NoProfile','-ExecutionPolicy','Bypass','-File','\"{_ps(str(archivo))}\"'")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", lanzar],
                       capture_output=True, text=True, timeout=300, creationflags=SIN_VENTANA)
    if r.returncode != 0:
        raise OSError("No se dio el permiso de administrador.")


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
    if SIN_AVISOS:
        return   # como servicio no hay pantalla: la ventana quedaria esperando para siempre
    if es_windows():
        import ctypes
        icono = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, mensaje, titulo, icono | 0x40000)  # MB_TOPMOST
    else:
        print(f"{titulo}: {mensaje}", file=sys.stderr)


# ------------------------------------------------------------ red
def nombre_equipo() -> str:
    return socket.gethostname().lower()


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
