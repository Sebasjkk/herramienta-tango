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
        "servidor": "http://desktop-b11ba4h:17000",
        "company": "3",
        "timeout_segundos": "30",
    },
    "programa": {
        "puerto": "8085",
        "vigencia_saldos_segundos": "60",
    },
}

COMENTARIO = """\
; Configuracion de Herramienta Tango.
; servidor: direccion del Tango (la misma que se usa en el navegador).
; company: ID interno de la empresa (se ve en la URL del Tango web: /company/3/...).
; puerto: puerto donde se abre la pagina para el celular.
; vigencia_saldos_segundos: cuanto tiempo se reutiliza la consulta de saldos.

"""


@dataclass(frozen=True)
class Config:
    servidor: str
    company: str
    timeout: int
    puerto: int
    vigencia_saldos: int


def cargar() -> Config:
    cfg = configparser.ConfigParser()
    cfg.read_dict(DEFECTO)
    if RUTA_CONFIG.exists():
        cfg.read(RUTA_CONFIG, encoding="utf-8")
    else:
        try:
            with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
                f.write(COMENTARIO)
                cfg.write(f)
        except OSError:
            pass
    return Config(
        servidor=cfg.get("tango", "servidor"),
        company=cfg.get("tango", "company"),
        timeout=cfg.getint("tango", "timeout_segundos"),
        puerto=cfg.getint("programa", "puerto"),
        vigencia_saldos=cfg.getint("programa", "vigencia_saldos_segundos"),
    )
