"""Arranque de Herramienta Tango."""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler

from . import NOMBRE, VERSION, config, credenciales
from .tango import ClienteTango, ServicioTango, TangoError
from .web.servidor import CARPETA_ESTATICA, crear_servidor

log = logging.getLogger("herramienta_tango")


def _configurar_log() -> None:
    log.setLevel(logging.INFO)
    formato = logging.Formatter("[%(asctime)s] %(message)s", "%d/%m %H:%M:%S")
    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(formato)
    log.addHandler(consola)
    try:
        archivo = RotatingFileHandler(config.RUTA_LOG, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        archivo.setFormatter(formato)
        log.addHandler(archivo)
    except OSError:
        log.warning("No se pudo crear el archivo de log; sigue solo en pantalla.")


def _direcciones_locales() -> list[str]:
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
    return sorted(ips)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="HerramientaTango", description=f"{NOMBRE} v{VERSION}")
    parser.add_argument("--nuevo-token", action="store_true", help="pedir el token de Tango de nuevo")
    parser.add_argument("--no-abrir", action="store_true", help="no abrir el navegador al iniciar")
    parser.add_argument("--version", action="version", version=f"{NOMBRE} {VERSION}")
    args = parser.parse_args(argv)

    _configurar_log()
    print(f"\n=== {NOMBRE} v{VERSION} (solo lectura) ===\n")

    if not (CARPETA_ESTATICA / "index.html").exists():
        log.error(f"Faltan las páginas web ({CARPETA_ESTATICA}). El programa está incompleto.")
        return 1

    cfg = config.cargar()
    token = credenciales.obtener_token(args.nuevo_token)
    servicio = ServicioTango(ClienteTango(cfg.servidor, cfg.company, token, cfg.timeout),
                             vigencia_saldos=cfg.vigencia_saldos)

    # Primera consulta: confirma que el token y la conexion funcionan
    try:
        saldos, _ = servicio.saldos_por_partida(forzar=True)
        con_saldo = sum(1 for s in saldos if abs(s.saldo) > 0.0001)
        log.info(f"Conectado a Tango: {len(saldos)} partidas ({con_saldo} con saldo)")
    except TangoError as e:
        log.error(str(e))
        print("\nEl programa sigue abierto, pero las páginas van a mostrar este error hasta que se resuelva.")

    try:
        servidor = crear_servidor(servicio, cfg.puerto)
    except OSError as e:
        log.error(f"No se pudo abrir el puerto {cfg.puerto}: {e}. "
                  "Puede que el programa ya esté abierto en otra ventana.")
        input("\nEnter para cerrar...")
        return 1

    print("\nAbrir desde el celular (conectado al Wi-Fi de la oficina):")
    for ip in _direcciones_locales():
        print(f"   http://{ip}:{cfg.puerto}")
    print(f"   http://{socket.gethostname()}:{cfg.puerto}")
    print("\nDejá esta ventana abierta. Para detener el programa, cerrala.\n")
    log.info(f"Escuchando en el puerto {cfg.puerto}")

    if not args.no_abrir:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{cfg.puerto}")).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0
