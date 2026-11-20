"""
Opciones de la Herramienta que valen para todos los equipos (se guardan en el
servidor, en opciones.json de la carpeta del programa).
"""

from __future__ import annotations

import json
import threading

from . import config

# Solo estas claves, con su valor por defecto
OPCIONES = {
    # Eliminar pedidos por la API: requiere la "API de Transacciones Tango Ventas",
    # que la licencia de Sianco no incluye (19/11/2026). Se activa si se compra.
    "pedidos_eliminar": False,
}

_lock = threading.Lock()


def _ruta():
    return config.CARPETA / "opciones.json"


def leer() -> dict:
    try:
        guardadas = json.loads(_ruta().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        guardadas = {}
    return {k: guardadas.get(k, v) for k, v in OPCIONES.items()}


def cambiar(clave: str, valor) -> dict:
    if clave not in OPCIONES:
        raise ValueError("Opción desconocida.")
    if not isinstance(valor, type(OPCIONES[clave])):
        raise ValueError("Valor inválido.")
    with _lock:
        actuales = leer()
        actuales[clave] = valor
        _ruta().parent.mkdir(parents=True, exist_ok=True)
        _ruta().write_text(json.dumps(actuales, indent=1), encoding="utf-8")
    return actuales
