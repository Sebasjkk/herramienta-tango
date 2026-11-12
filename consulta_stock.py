"""
Consulta de stock Sianco - saldos por partida desde Tango (SOLO LECTURA).

Corre en una PC de la oficina. Gustavo la abre desde el celular por el Wi-Fi.
El programa consulta a Tango por su API (consulta Live de saldos por partida)
y nunca escribe nada en Tango: solo hace pedidos GET.

El token de Tango se guarda cifrado en token.dat con DPAPI de Windows:
solo lo puede leer el mismo usuario de Windows en la misma PC.

Uso:
    ConsultaStockSianco.exe                 arranca normalmente
    ConsultaStockSianco.exe --nuevo-token   pide el token de nuevo
    ConsultaStockSianco.exe --no-abrir      no abre el navegador al iniciar

Solo usa la libreria estandar de Python (sin dependencias).
"""

from __future__ import annotations

import argparse
import configparser
import getpass
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from pathlib import Path

VERSION = "1.0"
NOMBRE = "Consulta de stock Sianco"

GUID_LEN = 36

# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #

def carpeta_programa() -> Path:
    """Carpeta donde viven config.ini, token.dat y el log (junto al .exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ruta_recurso(relativa: str) -> Path:
    """Archivos empaquetados dentro del .exe (la pagina web)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relativa


CARPETA = carpeta_programa()
RUTA_CONFIG = CARPETA / "config.ini"
RUTA_TOKEN = CARPETA / "token.dat"
RUTA_LOG = CARPETA / "consulta_stock.log"
RUTA_HTML = ruta_recurso("web/index.html")

# --------------------------------------------------------------------------- #
# Log
# --------------------------------------------------------------------------- #

log = logging.getLogger("consulta_stock")


def configurar_log() -> None:
    log.setLevel(logging.INFO)
    formato = logging.Formatter("[%(asctime)s] %(message)s", "%d/%m %H:%M:%S")
    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(formato)
    log.addHandler(consola)
    try:
        archivo = RotatingFileHandler(RUTA_LOG, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        archivo.setFormatter(formato)
        log.addHandler(archivo)
    except OSError:
        log.warning("No se pudo crear el archivo de log; sigue solo en pantalla.")

# --------------------------------------------------------------------------- #
# Configuracion
# --------------------------------------------------------------------------- #

CONFIG_DEFECTO = {
    "tango": {
        "servidor": "http://desktop-b11ba4h:17000",
        "company": "3",
        "proceso_saldos_partida": "17686",
        "timeout_segundos": "30",
    },
    "programa": {
        "puerto": "8085",
        "cache_segundos": "60",
    },
}

COMENTARIO_CONFIG = """\
; Configuracion de la Consulta de stock Sianco.
; servidor: direccion del Tango (la misma que se usa en el navegador).
; company: ID interno de la empresa (se ve en la URL del Tango web: /company/3/...).
; proceso_saldos_partida: consulta Live de saldos por partida (/company/3/live/17686).
; puerto: puerto donde se abre la pagina para el celular.
; cache_segundos: cuanto tiempo se reutiliza la ultima consulta a Tango.

"""


def cargar_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read_dict(CONFIG_DEFECTO)
    if RUTA_CONFIG.exists():
        cfg.read(RUTA_CONFIG, encoding="utf-8")
    else:
        try:
            with open(RUTA_CONFIG, "w", encoding="utf-8") as f:
                f.write(COMENTARIO_CONFIG)
                cfg.write(f)
        except OSError:
            pass
    return cfg

# --------------------------------------------------------------------------- #
# Token (DPAPI en Windows)
# --------------------------------------------------------------------------- #

def _dpapi(datos: bytes, cifrar: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(datos, len(datos))
    entrada = DATA_BLOB(len(datos), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    salida = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    funcion = crypt32.CryptProtectData if cifrar else crypt32.CryptUnprotectData
    ok = funcion(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida))
    if not ok:
        raise OSError("DPAPI no pudo procesar el token")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def guardar_token(token: str) -> None:
    datos = token.encode("utf-8")
    if os.name == "nt":
        RUTA_TOKEN.write_bytes(_dpapi(datos, cifrar=True))
    else:  # solo para pruebas fuera de Windows
        RUTA_TOKEN.write_bytes(datos)
        os.chmod(RUTA_TOKEN, 0o600)


def leer_token_guardado() -> str | None:
    if not RUTA_TOKEN.exists():
        return None
    try:
        datos = RUTA_TOKEN.read_bytes()
        if os.name == "nt":
            datos = _dpapi(datos, cifrar=False)
        return datos.decode("utf-8").strip()
    except Exception:
        log.warning("No se pudo leer token.dat (se guardó con otro usuario o en otra PC).")
        return None


def pedir_token() -> str:
    print()
    print("Hace falta el token de desarrollador de Tango.")
    print("Se genera en el Tango web: menú de usuario > Desarrollador > Generar > Aceptar.")
    while True:
        token = getpass.getpass("Pegá el token (no se muestra al escribir) y apretá Enter: ").strip()
        if len(token) == GUID_LEN and token.count("-") == 4:
            return token
        print(f"  Ese token tiene {len(token)} caracteres; debería tener {GUID_LEN} "
              "(formato XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX). Probá de nuevo.")


def obtener_token(forzar_nuevo: bool) -> str:
    if os.environ.get("SIANCO_TANGO_TOKEN"):  # solo para pruebas
        return os.environ["SIANCO_TANGO_TOKEN"].strip()
    if not forzar_nuevo:
        token = leer_token_guardado()
        if token:
            return token
    token = pedir_token()
    guardar_token(token)
    log.info("Token guardado cifrado en token.dat")
    return token

# --------------------------------------------------------------------------- #
# Cliente de Tango
# --------------------------------------------------------------------------- #

class TangoError(Exception):
    """Error al consultar Tango, con un mensaje pensado para mostrar."""


class ClienteTango:
    def __init__(self, servidor: str, company: str, token: str, timeout: int):
        self.servidor = servidor.rstrip("/")
        self.company = company
        self.token = token
        self.timeout = timeout

    def _get(self, ruta: str, parametros: dict) -> dict:
        url = f"{self.servidor}/{ruta}?{urllib.parse.urlencode(parametros)}"
        pedido = urllib.request.Request(url, method="GET", headers={
            "ApiAuthorization": self.token,
            "Company": self.company,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(pedido, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8-sig"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise TangoError("Tango rechazó el token (401). Borrá el archivo token.dat de la carpeta del programa, "
                                 "volvé a abrirlo y pegá un token aceptado en Tango (Desarrollador > Aceptar).") from None
            raise TangoError(f"Tango respondió con error HTTP {e.code}.") from None
        except urllib.error.URLError as e:
            raise TangoError(f"No se pudo conectar con Tango en {self.servidor} ({e.reason}).") from None
        except (TimeoutError, socket.timeout):
            raise TangoError("Tango tardó demasiado en responder.") from None
        except json.JSONDecodeError:
            raise TangoError("Tango respondió algo que no es JSON.") from None

    def consulta_live(self, proceso: str, tam_pagina: int = 500) -> list[dict]:
        filas: list[dict] = []
        pagina, total_paginas = 0, 1
        while pagina < total_paginas:
            datos = self._get("api/GetApiLiveQueryData", {
                "process": proceso, "pageSize": tam_pagina, "pageIndex": pagina,
            })
            if not datos.get("succeeded", False):
                raise TangoError(f"Tango no pudo ejecutar la consulta {proceso}: {datos.get('message')}")
            resultado = datos.get("resultData") or {}
            filas.extend(resultado.get("list") or [])
            total_paginas = int(resultado.get("totalPages") or 0)
            pagina += 1
        return filas

# --------------------------------------------------------------------------- #
# Saldos por partida
# --------------------------------------------------------------------------- #

def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def normalizar_partida(x: dict) -> dict:
    venc = _texto(x.get("FECHA_DE_VENCIMIENTO"))[:10] or None
    try:
        saldo = float(x.get("SALDO_CONTROL_STOCK") or 0)
    except (TypeError, ValueError):
        saldo = 0.0
    return {
        "id": x.get("ID_STA08"),
        "art": _texto(x.get("COD_ARTICULO")),
        "desc": _texto(x.get("DESCRIPCION")),
        "dep": _texto(x.get("DESCRIPCION_DEPOSITO")),
        "part": _texto(x.get("PARTIDA")),
        "desp": _texto(x.get("NUMERO_DE_DESPACHO")),
        "venc": venc,
        "um": _texto(x.get("UM_CONTROL_STOCK")),
        "s": round(saldo, 4),
    }


class CacheSaldos:
    """Guarda la ultima consulta para no pedirle lo mismo a Tango en cada busqueda."""

    def __init__(self, cliente: ClienteTango, proceso: str, segundos: int):
        self.cliente = cliente
        self.proceso = proceso
        self.segundos = segundos
        self._lock = threading.Lock()
        self._json: bytes | None = None
        self._hora = 0.0

    def obtener(self, forzar: bool = False) -> bytes:
        with self._lock:
            vigente = self._json is not None and (time.time() - self._hora) < self.segundos
            if vigente and not forzar:
                return self._json
            inicio = time.time()
            filas = [normalizar_partida(x) for x in self.cliente.consulta_live(self.proceso)]
            paquete = {
                "ok": True,
                "actualizado": datetime.now().isoformat(timespec="seconds"),
                "filas": filas,
            }
            self._json = json.dumps(paquete, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._hora = time.time()
            con_saldo = sum(1 for f in filas if abs(f["s"]) > 0.0001)
            log.info(f"Consulta a Tango: {len(filas)} partidas ({con_saldo} con saldo) "
                     f"en {time.time() - inicio:.1f} s")
            return self._json

# --------------------------------------------------------------------------- #
# Servidor web
# --------------------------------------------------------------------------- #

def crear_manejador(cache: CacheSaldos, html: bytes):
    class Manejador(BaseHTTPRequestHandler):
        server_version = f"ConsultaStockSianco/{VERSION}"

        def log_message(self, formato, *args):  # silencia el log por defecto
            pass

        def _responder(self, estado: int, tipo: str, cuerpo: bytes) -> None:
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _json_error(self, estado: int, mensaje: str) -> None:
            cuerpo = json.dumps({"ok": False, "error": mensaje}, ensure_ascii=False).encode("utf-8")
            self._responder(estado, "application/json; charset=utf-8", cuerpo)

        def do_GET(self):
            ruta = urllib.parse.urlparse(self.path)
            try:
                if ruta.path in ("/", "/index.html"):
                    self._responder(200, "text/html; charset=utf-8", html)
                elif ruta.path == "/api/saldos":
                    forzar = urllib.parse.parse_qs(ruta.query).get("refrescar") == ["1"]
                    self._responder(200, "application/json; charset=utf-8", cache.obtener(forzar))
                elif ruta.path == "/api/estado":
                    self._responder(200, "application/json; charset=utf-8",
                                    json.dumps({"ok": True, "version": VERSION}).encode())
                else:
                    self._responder(404, "text/plain; charset=utf-8", "No encontrado".encode("utf-8"))
            except TangoError as e:
                log.error(str(e))
                self._json_error(502, str(e))
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:  # no tirar abajo el servidor por un error puntual
                log.exception("Error inesperado")
                self._json_error(500, f"Error inesperado en el programa: {e.__class__.__name__}")

        def do_POST(self):
            self._responder(405, "text/plain; charset=utf-8", "Solo lectura".encode("utf-8"))

        do_PUT = do_DELETE = do_PATCH = do_POST

    return Manejador


def direcciones_locales() -> list[str]:
    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no envia nada; solo elige la interfaz
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)

# --------------------------------------------------------------------------- #
# Principal
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description=NOMBRE)
    parser.add_argument("--nuevo-token", action="store_true", help="pedir el token de Tango de nuevo")
    parser.add_argument("--no-abrir", action="store_true", help="no abrir el navegador al iniciar")
    args = parser.parse_args()

    configurar_log()
    print(f"\n=== {NOMBRE} v{VERSION} (solo lectura) ===\n")

    cfg = cargar_config()
    servidor = cfg.get("tango", "servidor")
    company = cfg.get("tango", "company")
    proceso = cfg.get("tango", "proceso_saldos_partida")
    timeout = cfg.getint("tango", "timeout_segundos")
    puerto = cfg.getint("programa", "puerto")
    cache_seg = cfg.getint("programa", "cache_segundos")

    if not RUTA_HTML.exists():
        log.error(f"Falta la página web ({RUTA_HTML}). El programa está incompleto.")
        return 1
    html = RUTA_HTML.read_bytes()

    token = obtener_token(args.nuevo_token)
    cliente = ClienteTango(servidor, company, token, timeout)
    cache = CacheSaldos(cliente, proceso, cache_seg)

    # Primera consulta: confirma que el token y la conexion funcionan
    try:
        cache.obtener(forzar=True)
    except TangoError as e:
        log.error(str(e))
        print("\nEl programa sigue abierto, pero la página va a mostrar este error hasta que se resuelva.")

    try:
        servidor_web = ThreadingHTTPServer(("0.0.0.0", puerto), crear_manejador(cache, html))
    except OSError as e:
        log.error(f"No se pudo abrir el puerto {puerto}: {e}. "
                  "Puede que el programa ya esté abierto en otra ventana.")
        input("\nEnter para cerrar...")
        return 1
    servidor_web.daemon_threads = True

    print("\nAbrir desde el celular (conectado al Wi-Fi de la oficina):")
    for ip in direcciones_locales():
        print(f"   http://{ip}:{puerto}")
    print(f"   http://{socket.gethostname()}:{puerto}")
    print("\nDejá esta ventana abierta. Para detener el programa, cerrala.\n")
    log.info(f"Escuchando en el puerto {puerto}")

    if not args.no_abrir:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{puerto}")).start()

    try:
        servidor_web.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor_web.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
