"""
Arranque de Herramienta Tango.

Corre con pythonw.exe (sin consola): al iniciarse abre el panel en el navegador.
Si ya hay una copia corriendo, solo abre su panel. La primera vez crea los
accesos directos. Los errores graves se muestran en una ventana de aviso de
Windows y todo queda registrado en herramienta_tango.log.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import NOMBRE, VERSION, config, sistema
from .actualizador import Actualizador, reiniciar
from .contexto import Contexto
from .web.servidor import CARPETA_ESTATICA, crear_servidor

log = logging.getLogger("herramienta_tango")


_HAY_CONSOLA = sys.stdout is not None


def _configurar_salida() -> None:
    # Con pythonw.exe no hay consola: stdout y stderr no existen y se descartan
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _configurar_log() -> None:
    log.setLevel(logging.INFO)
    formato = logging.Formatter("[%(asctime)s] %(message)s", "%d/%m %H:%M:%S")
    try:
        archivo = RotatingFileHandler(config.RUTA_LOG, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        archivo.setFormatter(formato)
        log.addHandler(archivo)
    except OSError:
        pass
    if _HAY_CONSOLA:
        consola = logging.StreamHandler(sys.stdout)
        consola.setFormatter(formato)
        log.addHandler(consola)


def _instancia_activa(puerto: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/estado", timeout=2) as r:
            return "version" in json.loads(r.read())
    except Exception:
        return False


def _abrir_panel(puerto: int) -> None:
    webbrowser.open(f"http://127.0.0.1:{puerto}/panel")


def main(argv: list[str] | None = None) -> int:
    _configurar_salida()
    parser = argparse.ArgumentParser(prog="HerramientaTango", description=f"{NOMBRE} v{VERSION}")
    parser.add_argument("--no-abrir", action="store_true", help="no abrir el panel en el navegador al iniciar")
    parser.add_argument("--escribir-version", metavar="ARCHIVO", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.escribir_version:  # lo usa el workflow para comprobar que el .exe arranca
        Path(args.escribir_version).write_text(VERSION, encoding="utf-8")
        return 0

    _configurar_log()
    log.info(f"=== {NOMBRE} v{VERSION} ===")

    if not (CARPETA_ESTATICA / "panel.html").exists():
        sistema.aviso(NOMBRE, "El programa está incompleto: faltan las páginas web. Volvé a descargarlo.")
        return 1

    inst = sistema.instalacion()
    if inst:
        os.chdir(inst.raiz)   # que la carpeta app no quede "en uso" y se pueda reemplazar al actualizar
    primera_vez = not config.RUTA_CONFIG.exists()
    cfg = config.cargar()

    if _instancia_activa(cfg.puerto):
        log.info("Ya hay una copia corriendo: se abre su panel.")
        if not args.no_abrir:
            _abrir_panel(cfg.puerto)
        return 0

    contexto = Contexto(cfg)
    try:
        servidor = crear_servidor(contexto, cfg.puerto)
    except OSError as e:
        log.error(f"No se pudo abrir el puerto {cfg.puerto}: {e}")
        sistema.aviso(NOMBRE, f"No se pudo iniciar: el puerto {cfg.puerto} está ocupado por otro programa.\n\n"
                              f"Se puede cambiar el puerto en config.ini, en la carpeta del programa.")
        return 1

    reinicio: dict = {}

    def detener():
        threading.Thread(target=servidor.shutdown, daemon=True).start()

    def al_instalar():
        reinicio["pedido"] = True
        detener()

    contexto.al_cerrar = detener
    actualizador = Actualizador(VERSION, cfg.repo_actualizaciones, cfg.actualizacion_cada_minutos,
                                cfg.actualizacion_automatica, al_instalar,
                                raiz=inst.raiz if inst else None)
    contexto.actualizador = actualizador

    if primera_vez and inst:
        try:
            lugares = sistema.crear_accesos_directos()
            log.info(f"Accesos directos creados en: {', '.join(lugares)}")
        except Exception as e:
            log.warning(f"No se pudieron crear los accesos directos: {e}")

    configurado = contexto.cargar_guardado()
    if configurado:
        # La conexion con Tango se prueba en segundo plano para que el panel abra enseguida
        threading.Thread(target=contexto.probar_conexion, name="conexion-tango", daemon=True).start()

    if cfg.repo_actualizaciones:
        actualizador.iniciar()
    else:
        actualizador.estado.estado = "desactivado"

    if not args.no_abrir or not configurado:
        threading.Timer(0.8, lambda: _abrir_panel(cfg.puerto)).start()

    log.info(f"Escuchando en el puerto {cfg.puerto}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()

    if reinicio.get("pedido") and inst:
        log.info("Abriendo la versión nueva...")
        try:
            reiniciar(inst.comando + ["--no-abrir"], inst.raiz)
        except OSError as e:
            log.error(f"No se pudo abrir la versión nueva: {e}")
            sistema.aviso(NOMBRE, "Se instaló una versión nueva pero no se pudo abrir sola.\n"
                                  "Abrí Herramienta Tango desde el acceso directo del escritorio.")
    log.info("Programa cerrado.")
    return 0
