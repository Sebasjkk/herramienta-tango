"""
Servidor web de la herramienta (red local).

API propia, de solo lectura sobre Tango, para que cualquier pagina o programa
de la empresa consulte Tango sin conocer su API:

    GET /api/estado                  version y estado de las actualizaciones
    GET /api/stock/partidas          saldos por partida
    GET /api/articulos
    GET /api/depositos
    GET /api/clientes
    GET /api/pedidos
    GET /api/listas-precios
    GET /api/ventas?desde=AAAA-MM-DD&hasta=AAAA-MM-DD

Con ?refrescar=1 se saltea la cache. Las respuestas tienen la forma
{"ok": true, "actualizado": "...", "datos": [...]}, o {"ok": false, "error": "..."}.

Panel de la PC (solo desde la misma PC donde corre el programa):

    GET  /panel                       pagina del panel
    GET  /api/sistema                 estado completo
    POST /api/sistema/configurar      {"servidor": "...", "token": "..."}
    POST /api/sistema/probar          vuelve a probar la conexion con Tango
    POST /api/sistema/inicio-automatico   {"activo": true|false}
    POST /api/sistema/buscar-actualizacion
    POST /api/sistema/cerrar

Los POST exigen el encabezado X-Herramienta-Tango, para que una pagina web
cualquiera abierta en la PC no pueda dispararlos.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
import urllib.parse
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .. import VERSION, sistema
from ..config import ruta_recurso
from ..tango import TangoError

log = logging.getLogger("herramienta_tango")

CARPETA_ESTATICA = ruta_recurso("herramienta_tango/web/estatico")
MAX_DIAS_VENTAS = 366
MAX_CUERPO = 10_000
ENCABEZADO_PANEL = "X-Herramienta-Tango"
DIRECCIONES_LOCALES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


class PedidoInvalido(Exception):
    pass


def _a_json(valor) -> object:
    if is_dataclass(valor):
        return asdict(valor)
    if isinstance(valor, (list, tuple)):
        return [_a_json(v) for v in valor]
    return valor


def _fecha_param(qs: dict, nombre: str, defecto: date) -> date:
    valor = (qs.get(nombre) or [""])[0]
    if not valor:
        return defecto
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise PedidoInvalido(f"La fecha '{nombre}' tiene que tener el formato AAAA-MM-DD.") from None


def crear_rutas(contexto) -> dict[str, Callable[[dict, bool], tuple]]:
    s = contexto.servicio

    def ventas(qs: dict, forzar: bool):
        hasta = _fecha_param(qs, "hasta", date.today())
        desde = _fecha_param(qs, "desde", hasta - timedelta(days=30))
        if desde > hasta:
            raise PedidoInvalido("'desde' no puede ser posterior a 'hasta'.")
        if (hasta - desde).days > MAX_DIAS_VENTAS:
            raise PedidoInvalido(f"El rango de fechas no puede superar {MAX_DIAS_VENTAS} días.")
        return s().ventas(desde, hasta, forzar)

    return {
        "/api/stock/partidas": lambda qs, f: s().saldos_por_partida(f),
        "/api/articulos": lambda qs, f: s().articulos(f),
        "/api/depositos": lambda qs, f: s().depositos(f),
        "/api/clientes": lambda qs, f: s().clientes(f),
        "/api/pedidos": lambda qs, f: s().pedidos(f),
        "/api/listas-precios": lambda qs, f: s().listas_precios(f),
        "/api/ventas": ventas,
    }


def crear_manejador(contexto):
    from ..contexto import NoConfigurado

    rutas = crear_rutas(contexto)
    raiz_estatica = CARPETA_ESTATICA.resolve()

    def accion_configurar(datos: dict) -> tuple[int, dict]:
        ok, mensaje = contexto.configurar(str(datos.get("servidor", "")), str(datos.get("token", "")))
        return (200 if ok else 400), {"ok": ok, "mensaje": mensaje, "sistema": contexto.info()}

    def accion_probar(datos: dict) -> tuple[int, dict]:
        contexto.probar_conexion()
        return 200, {"ok": True, "sistema": contexto.info()}

    def accion_inicio(datos: dict) -> tuple[int, dict]:
        try:
            sistema.activar_inicio_automatico(bool(datos.get("activo")))
        except OSError as e:
            return 400, {"ok": False, "mensaje": f"No se pudo cambiar: {e}"}
        return 200, {"ok": True, "sistema": contexto.info()}

    def accion_actualizacion(datos: dict) -> tuple[int, dict]:
        if not contexto.actualizador:
            return 400, {"ok": False, "mensaje": "Las actualizaciones están desactivadas."}
        threading.Thread(target=contexto.actualizador.revisar, daemon=True).start()
        return 200, {"ok": True, "mensaje": "Buscando actualizaciones..."}

    def accion_cerrar(datos: dict) -> tuple[int, dict]:
        threading.Timer(0.5, contexto.al_cerrar).start()
        return 200, {"ok": True, "mensaje": "El programa se está cerrando."}

    acciones = {
        "/api/sistema/configurar": accion_configurar,
        "/api/sistema/probar": accion_probar,
        "/api/sistema/inicio-automatico": accion_inicio,
        "/api/sistema/buscar-actualizacion": accion_actualizacion,
        "/api/sistema/cerrar": accion_cerrar,
    }

    class Manejador(BaseHTTPRequestHandler):
        server_version = f"HerramientaTango/{VERSION}"

        def log_message(self, formato, *args):
            pass

        # --------------------------------------------------------- utilidades
        def _es_local(self) -> bool:
            return self.client_address[0] in DIRECCIONES_LOCALES

        def _responder(self, estado: int, tipo: str, cuerpo: bytes, extra: dict | None = None) -> None:
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(cuerpo)

        def _json(self, estado: int, contenido: dict) -> None:
            cuerpo = json.dumps(contenido, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._responder(estado, "application/json; charset=utf-8", cuerpo)

        def _estatico(self, relativa: str) -> None:
            archivo = (raiz_estatica / relativa).resolve()
            if raiz_estatica not in archivo.parents or not archivo.is_file():
                self._responder(404, "text/plain; charset=utf-8", "No encontrado".encode())
                return
            tipo = mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
            if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
                tipo += "; charset=utf-8"
            self._responder(200, tipo, archivo.read_bytes())

        # --------------------------------------------------------- GET
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(url.query)
            try:
                if url.path == "/api/estado":
                    act = contexto.actualizador.estado.como_dict() if contexto.actualizador else None
                    self._json(200, {"ok": True, "version": VERSION, "configurado": contexto.configurado,
                                     "actualizacion": act})
                elif url.path == "/api/sistema":
                    if not self._es_local():
                        self._json(403, {"ok": False, "error": "Solo desde la PC donde está instalado el programa."})
                    else:
                        self._json(200, {"ok": True, **contexto.info()})
                elif url.path in rutas:
                    forzar = qs.get("refrescar") == ["1"]
                    datos, momento = rutas[url.path](qs, forzar)
                    self._json(200, {
                        "ok": True,
                        "actualizado": datetime.fromtimestamp(momento).isoformat(timespec="seconds"),
                        "datos": _a_json(datos),
                    })
                elif url.path.startswith("/api/"):
                    self._json(404, {"ok": False, "error": "Esa consulta no existe."})
                elif url.path in ("/panel", "/panel/"):
                    if self._es_local():
                        self._estatico("panel.html")
                    else:
                        self._responder(302, "text/plain; charset=utf-8", b"", {"Location": "/"})
                elif url.path in ("", "/"):
                    self._estatico("index.html")
                else:
                    self._estatico(url.path.lstrip("/"))
            except PedidoInvalido as e:
                self._json(400, {"ok": False, "error": str(e)})
            except NoConfigurado as e:
                self._json(503, {"ok": False, "error": str(e)})
            except TangoError as e:
                log.error(str(e))
                self._json(502, {"ok": False, "error": str(e)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                log.exception("Error inesperado")
                self._json(500, {"ok": False, "error": f"Error inesperado en el programa: {e.__class__.__name__}"})

        # --------------------------------------------------------- POST (solo panel)
        def do_POST(self):
            url = urllib.parse.urlparse(self.path)
            accion = acciones.get(url.path)
            if accion is None:
                self._json(405, {"ok": False, "error": "Solo lectura."})
                return
            if not self._es_local():
                self._json(403, {"ok": False, "error": "Solo desde la PC donde está instalado el programa."})
                return
            if self.headers.get(ENCABEZADO_PANEL) != "1":
                self._json(403, {"ok": False, "error": "Pedido no permitido."})
                return
            try:
                largo = int(self.headers.get("Content-Length") or 0)
                if largo > MAX_CUERPO:
                    self._json(413, {"ok": False, "error": "Pedido demasiado grande."})
                    return
                cuerpo = self.rfile.read(largo) if largo else b"{}"
                datos = json.loads(cuerpo.decode("utf-8") or "{}")
                if not isinstance(datos, dict):
                    raise ValueError
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"ok": False, "error": "Pedido inválido."})
                return
            try:
                estado, respuesta = accion(datos)
                self._json(estado, respuesta)
            except Exception as e:
                log.exception("Error en acción del panel")
                self._json(500, {"ok": False, "mensaje": f"Error inesperado: {e.__class__.__name__}"})

        def _no_permitido(self):
            self._json(405, {"ok": False, "error": "Solo lectura."})

        do_PUT = do_PATCH = do_DELETE = _no_permitido

    return Manejador


def crear_servidor(contexto, puerto: int) -> ThreadingHTTPServer:
    servidor = ThreadingHTTPServer(("0.0.0.0", puerto), crear_manejador(contexto))
    servidor.daemon_threads = True
    return servidor
