"""
Servidor web de la herramienta (red local, solo lectura).

Expone una API propia con nombres claros, para que cualquier pagina o programa
de la empresa consulte Tango sin conocer su API:

    GET /api/estado                  version y estado de las actualizaciones
    GET /api/stock/partidas          saldos por partida
    GET /api/articulos
    GET /api/depositos
    GET /api/clientes
    GET /api/pedidos
    GET /api/listas-precios
    GET /api/ventas?desde=AAAA-MM-DD&hasta=AAAA-MM-DD

Con ?refrescar=1 se saltea la cache. Todas las respuestas tienen la forma
{"ok": true, "actualizado": "...", "datos": [...]}, o {"ok": false, "error": "..."}.
Cualquier metodo distinto de GET responde 405.

Las paginas para el celular se sirven desde la carpeta "estatico".
"""

from __future__ import annotations

import json
import logging
import mimetypes
import urllib.parse
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from .. import VERSION
from ..config import ruta_recurso
from ..tango import ServicioTango, TangoError

log = logging.getLogger("herramienta_tango")

CARPETA_ESTATICA = ruta_recurso("herramienta_tango/web/estatico")
MAX_DIAS_VENTAS = 366


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


def crear_rutas(servicio: ServicioTango) -> dict[str, Callable[[dict, bool], tuple]]:
    def ventas(qs: dict, forzar: bool):
        hasta = _fecha_param(qs, "hasta", date.today())
        desde = _fecha_param(qs, "desde", hasta - timedelta(days=30))
        if desde > hasta:
            raise PedidoInvalido("'desde' no puede ser posterior a 'hasta'.")
        if (hasta - desde).days > MAX_DIAS_VENTAS:
            raise PedidoInvalido(f"El rango de fechas no puede superar {MAX_DIAS_VENTAS} días.")
        return servicio.ventas(desde, hasta, forzar)

    return {
        "/api/stock/partidas": lambda qs, f: servicio.saldos_por_partida(f),
        "/api/articulos": lambda qs, f: servicio.articulos(f),
        "/api/depositos": lambda qs, f: servicio.depositos(f),
        "/api/clientes": lambda qs, f: servicio.clientes(f),
        "/api/pedidos": lambda qs, f: servicio.pedidos(f),
        "/api/listas-precios": lambda qs, f: servicio.listas_precios(f),
        "/api/ventas": ventas,
    }


def crear_manejador(servicio: ServicioTango, estado_extra: Callable[[], dict] | None = None):
    rutas = crear_rutas(servicio)
    raiz_estatica = CARPETA_ESTATICA.resolve()

    class Manejador(BaseHTTPRequestHandler):
        server_version = f"HerramientaTango/{VERSION}"

        def log_message(self, formato, *args):
            pass

        def _responder(self, estado: int, tipo: str, cuerpo: bytes) -> None:
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(cuerpo)

        def _json(self, estado: int, contenido: dict) -> None:
            cuerpo = json.dumps(contenido, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._responder(estado, "application/json; charset=utf-8", cuerpo)

        def _estatico(self, ruta: str) -> None:
            relativa = "index.html" if ruta in ("", "/") else ruta.lstrip("/")
            archivo = (raiz_estatica / relativa).resolve()
            if raiz_estatica not in archivo.parents or not archivo.is_file():
                self._responder(404, "text/plain; charset=utf-8", "No encontrado".encode())
                return
            tipo = mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
            if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
                tipo += "; charset=utf-8"
            self._responder(200, tipo, archivo.read_bytes())

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(url.query)
            try:
                if url.path == "/api/estado":
                    estado = {"ok": True, "version": VERSION}
                    if estado_extra:
                        estado.update(estado_extra())
                    self._json(200, estado)
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
                else:
                    self._estatico(url.path)
            except PedidoInvalido as e:
                self._json(400, {"ok": False, "error": str(e)})
            except TangoError as e:
                log.error(str(e))
                self._json(502, {"ok": False, "error": str(e)})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                log.exception("Error inesperado")
                self._json(500, {"ok": False, "error": f"Error inesperado en el programa: {e.__class__.__name__}"})

        def _solo_lectura(self):
            self._json(405, {"ok": False, "error": "Solo lectura."})

        do_POST = do_PUT = do_PATCH = do_DELETE = _solo_lectura

    return Manejador


def crear_servidor(servicio: ServicioTango, puerto: int,
                   estado_extra: Callable[[], dict] | None = None) -> ThreadingHTTPServer:
    servidor = ThreadingHTTPServer(("0.0.0.0", puerto), crear_manejador(servicio, estado_extra))
    servidor.daemon_threads = True
    return servidor
