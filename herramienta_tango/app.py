"""
Arranque de Herramienta Tango.

Corre con pythonw.exe (sin consola): al iniciarse abre el panel en el navegador.
Si ya hay una copia corriendo, solo abre su panel. La primera vez crea los
accesos directos. Los errores graves se muestran en una ventana de aviso de
Windows y todo queda registrado en herramienta_tango.log.

Modo servidor (--servicio): lo arranca una tarea programada de Windows con la
cuenta SYSTEM. Este proceso solo vigila: abre el programa como proceso hijo y lo
vuelve a abrir si se cierra por un error o despues de instalar una version
nueva. Se detiene si el programa se cierra a pedido (boton Cerrar o Desactivar).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
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


# Codigos de salida del programa cuando corre bajo el vigilante del modo servidor
SALIDA_REINICIAR = 3    # se instalo una version nueva
SALIDA_DETENER = 4      # se cerro a pedido: el vigilante tambien termina


def _vigilar() -> int:
    """Modo servidor: abre el programa y lo mantiene abierto."""
    sistema.SIN_AVISOS = True
    inst = sistema.instalacion()
    comando = inst.comando if inst else [sys.executable, str(config.CARPETA_CODIGO / "HerramientaTango.pyw")]
    carpeta = str(inst.raiz if inst else config.CARPETA)
    log.info("Modo servidor: vigilante en marcha.")
    seguidos = 0
    while True:
        inicio = time.monotonic()
        codigo = subprocess.call(comando + ["--no-abrir", "--hijo-servicio"], cwd=carpeta,
                                 creationflags=sistema.SIN_VENTANA)
        if codigo == SALIDA_DETENER:
            log.info("Modo servidor: el programa se cerró a pedido.")
            return 0
        if codigo == SALIDA_REINICIAR:
            seguidos = 0
            continue
        # Error, o el puerto lo tiene otra copia: esperar y reintentar (cada vez mas espaciado)
        seguidos = seguidos + 1 if time.monotonic() - inicio < 60 else 1
        espera = min(10 * seguidos, 300)
        log.warning(f"Modo servidor: el programa terminó con código {codigo}; se reabre en {espera} s.")
        time.sleep(espera)


def _abrir_panel(puerto: int) -> None:
    webbrowser.open(f"http://127.0.0.1:{puerto}/panel")


def main(argv: list[str] | None = None) -> int:
    _configurar_salida()
    parser = argparse.ArgumentParser(prog="HerramientaTango", description=f"{NOMBRE} v{VERSION}")
    parser.add_argument("--no-abrir", action="store_true", help="no abrir el panel en el navegador al iniciar")
    parser.add_argument("--servicio", action="store_true", help="modo servidor (lo usa la tarea programada)")
    parser.add_argument("--hijo-servicio", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--escribir-version", metavar="ARCHIVO", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.escribir_version:  # lo usa el workflow para comprobar que el .exe arranca
        Path(args.escribir_version).write_text(VERSION, encoding="utf-8")
        return 0

    _configurar_log()
    if args.servicio:
        inst = sistema.instalacion()
        if inst:
            os.chdir(inst.raiz)
        return _vigilar()
    como_servicio = args.hijo_servicio
    if como_servicio:
        sistema.SIN_AVISOS = True
        args.no_abrir = True
    log.info(f"=== {NOMBRE} v{VERSION}{' (modo servidor)' if como_servicio else ''} ===")

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
    contexto.como_servicio = como_servicio
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

    if primera_vez and inst and not como_servicio:
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

    if not como_servicio and (not args.no_abrir or not configurado):
        threading.Timer(0.8, lambda: _abrir_panel(cfg.puerto)).start()

    log.info(f"Escuchando en el puerto {cfg.puerto}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()

    if como_servicio:
        # El vigilante vuelve a abrir el programa (con la version nueva) o termina
        log.info("Programa cerrado.")
        return SALIDA_REINICIAR if reinicio.get("pedido") else SALIDA_DETENER

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
