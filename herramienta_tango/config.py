"""Rutas de trabajo y archivo config.ini."""

from __future__ import annotations

import configparser
import sys
from dataclasses import dataclass
from pathlib import Path


def carpeta_programa() -> Path:
    """Carpeta donde viven config.ini, token.dat y el log (junto al .exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def ruta_recurso(relativa: str) -> Path:
    """Archivos empaquetados con el programa (paginas web)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / relativa


CARPETA = carpeta_programa()
RUTA_CONFIG = CARPETA / "config.ini"
RUTA_TOKEN = CARPETA / "token.dat"
RUTA_LOG = CARPETA / "herramienta_tango.log"

DEFECTO = {
    "tango": {
        "servidor": "",
        "company": "",
        "timeout_segundos": "30",
    },
    "programa": {
        "puerto": "8085",
        "vigencia_saldos_segundos": "60",
    },
    "actualizaciones": {
        "repositorio": "Sebasjkk/herramienta-tango",
        "automatica": "si",
        "cada_minutos": "15",
    },
}

COMENTARIO = """\
; Configuracion de Herramienta Tango.
; servidor: direccion del Tango (la misma que se usa en el navegador).
; company: ID interno de la empresa (se ve en la URL del Tango web: /company/NUMERO/...).
; puerto: puerto donde se abre la pagina para el celular.
; vigencia_saldos_segundos: cuanto tiempo se reutiliza la consulta de saldos.
; actualizaciones: de que repositorio de GitHub se bajan las versiones nuevas,
;   si se instalan solas (si / no) y cada cuantos minutos se revisa.

"""


@dataclass(frozen=True)
class Config:
    servidor: str
    company: str
    timeout: int
    puerto: int
    vigencia_saldos: int
    repo_actualizaciones: str
    actualizacion_automatica: bool
    actualizacion_cada_minutos: int


def _preguntar_servidor() -> str:
    print("Falta la dirección del servidor de Tango.")
    print("Es la misma que se ve en el navegador al abrir el Tango web, por ejemplo http://NOMBRE-PC:17000")
    while True:
        valor = input("Dirección del servidor: ").strip().rstrip("/")
        if valor and not valor.lower().startswith(("http://", "https://")):
            valor = "http://" + valor
        if valor.count(":") >= 2:  # esquema + puerto
            # Si pegaron una URL completa del Tango web, quedarse con servidor y puerto
            partes = valor.split("/")
            return "/".join(partes[:3])
        print("  Tiene que incluir el puerto, por ejemplo http://NOMBRE-PC:17000. Probá de nuevo.")


def _preguntar_company() -> str:
    print("Falta el número de empresa.")
    print("Se ve en la dirección del Tango web: .../company/NUMERO/...")
    while True:
        valor = input("Número de empresa: ").strip()
        if valor.isdigit():
            return valor
        print("  Tiene que ser un número. Probá de nuevo.")


def cargar() -> Config:
    cfg = configparser.ConfigParser()
    cfg.read_dict(DEFECTO)
    if RUTA_CONFIG.exists():
        cfg.read(RUTA_CONFIG, encoding="utf-8")

    cambio = not RUTA_CONFIG.exists()
    if not cfg.get("tango", "servidor").strip():
        print()
        cfg.set("tango", "servidor", _preguntar_servidor())
        cambio = True
    if not cfg.get("tango", "company").strip():
        print()
        cfg.set("tango", "company", _preguntar_company())
        cambio = True
    if cambio:
        try:
            with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
                f.write(COMENTARIO)
                cfg.write(f)
            print(f"Configuración guardada en {RUTA_CONFIG.name}")
        except OSError:
            pass
    return Config(
        servidor=cfg.get("tango", "servidor"),
        company=cfg.get("tango", "company"),
        timeout=cfg.getint("tango", "timeout_segundos"),
        puerto=cfg.getint("programa", "puerto"),
        vigencia_saldos=cfg.getint("programa", "vigencia_saldos_segundos"),
        repo_actualizaciones=cfg.get("actualizaciones", "repositorio"),
        actualizacion_automatica=cfg.get("actualizaciones", "automatica").strip().lower() in ("si", "sí", "s", "true", "1"),
        actualizacion_cada_minutos=cfg.getint("actualizaciones", "cada_minutos"),
    )
