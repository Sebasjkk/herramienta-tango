"""Rutas de trabajo y archivo config.ini."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


# Estructura instalada:
#   <raiz>\python\        Python oficial (pythonw.exe, firmado)
#   <raiz>\app\           codigo del programa (se reemplaza en cada actualizacion)
#   <raiz>\config.ini, token.dat, herramienta_tango.log   datos (no se tocan al actualizar)
# En desarrollo (sin carpeta app) todo vive en la carpeta del repositorio.
CARPETA_CODIGO = Path(__file__).resolve().parent.parent


def carpeta_programa() -> Path:
    """Carpeta donde viven config.ini, token.dat y el log."""
    return CARPETA_CODIGO.parent if CARPETA_CODIGO.name == "app" else CARPETA_CODIGO


def ruta_recurso(relativa: str) -> Path:
    """Archivos que vienen con el codigo (paginas web, icono)."""
    return CARPETA_CODIGO / relativa


CARPETA = carpeta_programa()
RUTA_CONFIG = CARPETA / "config.ini"
RUTA_TOKEN = CARPETA / "token.dat"
RUTA_LOG = CARPETA / "herramienta_tango.log"

DEFECTO = {
    "tango": {
        "servidor": "",          # se completa desde el panel la primera vez
        "company": "3",
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
; Configuracion de Herramienta Tango. Lo normal es configurarla desde el panel
; (se abre en el navegador al iniciar el programa); este archivo es para ajustes finos.
; servidor: direccion del Tango (la misma que se usa en el navegador).
; company: ID interno de la empresa en Tango.
; puerto: puerto donde se abren el panel y la pagina para el celular.
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


def normalizar_servidor(texto: str) -> str:
    """Acepta 'nombre-pc:17000', 'http://nombre-pc:17000' o una URL completa del Tango web."""
    valor = (texto or "").strip()
    if not valor:
        return ""
    if not valor.lower().startswith(("http://", "https://")):
        valor = "http://" + valor
    partes = valor.split("/")
    return "/".join(partes[:3])


def servidor_valido(servidor: str) -> bool:
    host = servidor.split("//", 1)[-1]
    return bool(host) and ":" in host and host.rsplit(":", 1)[1].isdigit()


def _leer() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read_dict(DEFECTO)
    if RUTA_CONFIG.exists():
        cfg.read(RUTA_CONFIG, encoding="utf-8")
    return cfg


def _escribir(cfg: configparser.ConfigParser) -> None:
    with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
        f.write(COMENTARIO)
        cfg.write(f)


def cargar() -> Config:
    cfg = _leer()
    if not RUTA_CONFIG.exists():
        try:
            _escribir(cfg)
        except OSError:
            pass
    return Config(
        servidor=normalizar_servidor(cfg.get("tango", "servidor")),
        company=cfg.get("tango", "company").strip() or "3",
        timeout=cfg.getint("tango", "timeout_segundos"),
        puerto=cfg.getint("programa", "puerto"),
        vigencia_saldos=cfg.getint("programa", "vigencia_saldos_segundos"),
        repo_actualizaciones=cfg.get("actualizaciones", "repositorio").strip(),
        actualizacion_automatica=cfg.get("actualizaciones", "automatica").strip().lower() in ("si", "sí", "s", "true", "1"),
        actualizacion_cada_minutos=cfg.getint("actualizaciones", "cada_minutos"),
    )


def guardar_servidor(servidor: str) -> None:
    cfg = _leer()
    cfg.set("tango", "servidor", servidor)
    _escribir(cfg)
