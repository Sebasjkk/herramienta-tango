"""
Servidor web de la herramienta (red local).

API propia, de solo lectura sobre Tango, para que cualquier pagina o programa
de la empresa consulte Tango sin conocer su API:

    GET /api/estado                  version y estado de las actualizaciones
    GET /api/stock/partidas          saldos por partida
    GET /api/stock/articulos         saldos por articulo y deposito (tambien los que no llevan partidas)
    GET /api/articulos
    GET /api/depositos
    GET /api/clientes
    GET /api/pedidos
    GET /api/pedidos/<id>            detalle completo (renglones con entregado y falta, notas, lista, cliente)
    GET /api/pedidos/avance          cuanto se entrego de cada pedido pendiente (sin entregar / parcial / entregado)
    GET /api/pedidos/<id>/remitos    remitos y devoluciones hechos contra el pedido (base, solo lectura)
    GET/POST /api/opciones           opciones para todos los equipos ({"clave", "valor"})
    POST /api/pedidos/eliminar       {"id": n, "confirmar": "31"}   copia en cambios_pedidos.jsonl
    GET /api/listas-precios
    GET /api/precios                 precios vigentes de todas las listas
    GET /api/ventas?desde=AAAA-MM-DD&hasta=AAAA-MM-DD

Listas de precios (leidas de las tablas de Tango, no de la consulta 12742):

    GET /api/listas                  listas con cantidad de articulos y clientes asignados
    GET /api/listas/<id>             articulos de una lista, con precios especiales por cliente
    GET /api/articulos/<codigo>/precios   en que listas esta un articulo
    GET /api/articulos/<codigo>/cotizaciones   cotizaciones donde aparece (con cantidad y precio)
    GET /api/valorizacion            stock de Central valorizado en USD, renglon por renglon (base, solo lectura)
    GET /api/valorizacion/aduana?carpeta=N  diagnostico: comprobantes de Aduana de una carpeta y sus cuentas
    GET /api/precio-sugerido?art=&cliente=  ventas del articulo, precio en la lista del cliente (solo lectura)
    GET /api/precio-sugerido/costo?art=     costo unitario en USD (valorizacion o ultima importacion)
    GET /valorizacion.xlsx           lo mismo en Excel
    GET /api/importaciones           carpetas de importacion y, por articulo, en camino y precio de compra (base, solo lectura)
    GET /api/articulos/<codigo>/movimientos    ultimos movimientos de stock (base, solo lectura)
    POST /api/inventario/comparar    {"nombre", "archivo": base64 del .xls/.xlsx de inventario} -> diferencias con Tango + Excel
    POST /api/exportar               {"nombre", "columnas": [{"titulo", "tipo"}], "filas": [[...]]} -> .xlsx
    GET /api/cotizaciones            todas las cotizaciones (consulta 17948)
    GET /api/cotizaciones/<numero>/renglones
    GET /api/listas/<id>/comprobantes?anio=  comprobantes de venta de un año con esa lista (base, solo lectura)
    GET /api/base/{usos,comprobantes,renglones}  lo mismo, para la Herramienta de otra PC
    GET /api/comprobantes/renglones?t=&n=   renglones de un comprobante (base, solo lectura)
    GET /cotizacion/<id>.pdf         el PDF del formulario 128, como lo imprime Tango
    GET /api/remitos                 remitos del ultimo año (consulta 17965), con la OC del pedido
    GET /api/remitos/vista           los mismos, con todos sus pedidos (relacion leida de la base)
    GET /api/remitos/<id>/renglones  articulos y partidas de un remito (base, solo lectura)
    GET /api/clientes/<id>/envio     direcciones de entrega y contacto, para las etiquetas
    GET /api/precios/cambios         registro de cambios hechos desde la herramienta
    GET /api/mezclas                 mezclas de polvos cargadas (historial)
    GET /mezclas/planilla.xlsx?ids=1,2   planilla de Egresos de Stock para importar en Tango
    GET /api/sesion                  si se pueden modificar precios y quien esta adentro

Modificar precios (cualquier equipo de la red; el encabezado X-Nombre, opcional,
dice quien hace el cambio y queda en el registro junto con la IP):

    POST /api/precios/cambiar        {"renglon": id, "precio": n, "cliente": id_cliente|null}
    POST /api/precios/agregar        {"lista": id, "articulo": "codigo", "precio": n, "cliente": id|null, "codigo_cliente": "..."}
    POST /api/precios/quitar         {"renglon": id}
    POST /api/listas/crear           {"nombre": "...", "moneda": "$"|"US$", "numero": n|null, "cliente": id|null}
    POST /api/listas/asignar         {"lista": id, "cliente": id}   cambia la lista en la ficha del cliente
    POST /api/listas/importar/analizar  {"archivo": base64 del .xlsx}   vista previa, no escribe
    POST /api/listas/importar/aplicar   {"plan": id, "actualizar_distintos": bool, "saltear_observaciones": bool}
    GET  /api/listas/importar/estado    avance de la importacion
    POST /api/mezclas/crear          {"referencia": "...", "renglones": [{"articulo", "partida", "cantidad"}]}
    POST /api/mezclas/subidas        {"ids": [..]}   ya se importaron en Tango
    POST /api/mezclas/borrar         {"id": n}       solo las que no se subieron
    POST /api/listas/eliminar        {"lista": id, "confirmar": "NOMBRE"}

Con ?refrescar=1 se saltea la cache. Las respuestas tienen la forma
{"ok": true, "actualizado": "...", "datos": [...]}, o {"ok": false, "error": "..."}.

Panel de la PC (solo desde la misma PC donde corre el programa):

    GET  /panel                       pagina del panel
    GET  /api/sistema                 estado completo
    POST /api/sistema/configurar      {"servidor": "...", "token": "..."}
    POST /api/sistema/probar          vuelve a probar la conexion con Tango
    POST /api/sistema/inicio-automatico   {"activo": true|false}
    POST /api/sistema/buscar-actualizacion
    POST /api/sistema/accesos-directos   crea los accesos directos de nuevo
    POST /api/sistema/modo-servidor   {"activo": true|false}

Para las otras PCs:
    GET /acceso-directo.url           acceso directo de Windows que abre el menu
    POST /api/sistema/cerrar

Los POST exigen el encabezado X-Herramienta-Tango, para que una pagina web
cualquiera abierta en la PC no pueda dispararlos.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import mimetypes
import threading
import urllib.parse
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

import time

from .. import VERSION, opciones, sistema
from ..precios import PedidoInvalido as DatoInvalido
from ..config import ruta_recurso
from ..tango import TangoError

log = logging.getLogger("herramienta_tango")

CARPETA_ESTATICA = ruta_recurso("herramienta_tango/web/estatico")
TIPOS = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
         ".png": "image/png", ".ico": "image/x-icon", ".svg": "image/svg+xml"}
MAX_DIAS_VENTAS = 366
MAX_CUERPO = 10_000
MAX_CUERPO_ARCHIVO = 8_000_000      # Excel en base64 para importar listas, y datos para exportar
MAX_COLUMNAS_EXPORTAR = 30
MAX_CUERPO_INVENTARIO = 60_000_000   # el Excel de inventario pesa ~10 MB (tiene Ingresos y Egresos), en base64 ~14 MB
MAX_FILAS_RESPUESTA = 600            # renglones con diferencias que se mandan a la pantalla (el Excel lleva todos)
ENCABEZADO_PANEL = "X-Herramienta-Tango"
ENCABEZADO_NOMBRE = "X-Nombre"
DIRECCIONES_LOCALES = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


class PedidoInvalido(Exception):
    pass


RUTAS_APP = {"/api/precios/cambiar", "/api/precios/agregar", "/api/precios/quitar",
             "/api/listas/crear", "/api/listas/eliminar", "/api/listas/asignar",
             "/api/mezclas/crear", "/api/mezclas/subidas", "/api/mezclas/borrar",
             "/api/listas/importar/analizar", "/api/listas/importar/aplicar", "/api/listas/restaurar",
             "/api/pedidos/eliminar", "/api/opciones",
             "/api/precios/ajuste/vista-previa", "/api/precios/ajuste", "/api/precios/ajuste/revertir"}


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

    def importaciones(qs: dict, forzar: bool):
        from .. import base_tango
        try:
            return base_tango.importaciones_datos(forzar), time.time()
        except base_tango.BaseNoDisponible as e:
            raise PedidoInvalido(str(e)) from None

    def valorizacion(qs: dict, forzar: bool):
        from .. import base_tango
        try:
            return base_tango.valorizacion_datos(forzar), time.time()
        except base_tango.BaseNoDisponible as e:
            raise PedidoInvalido(str(e)) from None

    def aduana(qs: dict, forzar: bool):
        from .. import base_tango
        carpeta = (qs.get("carpeta") or [""])[0].strip()
        if not carpeta.isdigit():
            raise PedidoInvalido("Falta el número de carpeta.")
        try:
            return base_tango.aduana_carpeta(int(carpeta)), time.time()
        except ValueError as e:
            raise PedidoInvalido(str(e)) from None
        except base_tango.BaseNoDisponible as e:
            raise PedidoInvalido(str(e)) from None

    def precio_sugerido(qs: dict, forzar: bool):
        from .. import base_tango, precio_sugerido as ps
        art = (qs.get("art") or [""])[0].strip()
        if not art:
            raise PedidoInvalido("Falta el artículo.")
        try:
            return ps.armar(s(), art, (qs.get("cliente") or [""])[0]), time.time()
        except ValueError as e:
            raise PedidoInvalido(str(e)) from None

    def precio_sugerido_costo(qs: dict, forzar: bool):
        from .. import precio_sugerido as ps
        art = (qs.get("art") or [""])[0].strip()
        if not art:
            raise PedidoInvalido("Falta el artículo.")
        return ps.costo(s(), art), time.time()

    def _remitos_diag():
        from .. import base_tango, remitos as rem
        try:
            return rem.diagnostico(s()), time.time()
        except base_tango.BaseNoDisponible as e:
            raise PedidoInvalido(str(e)) from None

    def _remitos_vista(forzar: bool):
        from .. import remitos as rem
        return rem.vista(s(), forzar)

    return {
        "/api/stock/partidas": lambda qs, f: s().saldos_por_partida(f),
        "/api/stock/articulos": lambda qs, f: s().saldos_por_articulo(f),
        "/api/articulos": lambda qs, f: s().articulos(f),
        "/api/depositos": lambda qs, f: s().depositos(f),
        "/api/clientes": lambda qs, f: s().clientes(f),
        "/api/pedidos": lambda qs, f: s().pedidos(f),
        "/api/pedidos/avance": lambda qs, f: s().avance_pedidos(f),
        "/api/listas-precios": lambda qs, f: s().listas_precios(f),
        "/api/precios": lambda qs, f: s().precios(f),
        "/api/ventas": ventas,
        "/api/listas": lambda qs, f: (s().editor.listas(f), time.time()),
        "/api/cotizaciones": lambda qs, f: s().cotizaciones(f),
        "/api/remitos": lambda qs, f: s().remitos(f),
        "/api/remitos/vista": lambda qs, f: _remitos_vista(f),
        "/api/remitos/diagnostico": lambda qs, f: _remitos_diag(),
        "/api/precios/cambios": lambda qs, f: (s().editor.registro.ultimos(300), time.time()),
        "/api/mezclas": lambda qs, f: (s().mezclas.registro.todas(), time.time()),
        "/api/listas/importar/estado": lambda qs, f: (s().importador.estado(), time.time()),
        "/api/listas/restaurar/estado": lambda qs, f: (s().editor.estado_restauracion(), time.time()),
        "/api/precios/ajuste/estado": lambda qs, f: (s().editor.estado_ajuste(), time.time()),
        "/api/opciones": lambda qs, f: (opciones.leer(), time.time()),
        "/api/importaciones": importaciones,
        "/api/valorizacion": valorizacion,
        "/api/valorizacion/aduana": aduana,
        "/api/precio-sugerido": precio_sugerido,
        "/api/precio-sugerido/costo": precio_sugerido_costo,
    }


def ruta_variable(contexto, ruta: str):
    """/api/listas/<id> y /api/articulos/<codigo>/precios"""
    partes = ruta.strip("/").split("/")
    if len(partes) == 3 and partes[:2] == ["api", "listas"] and partes[2].isdigit():
        id_lista = int(partes[2])
        return lambda qs, f: (contexto.servicio().editor.lista(id_lista, f), time.time())
    if len(partes) == 4 and partes[:2] == ["api", "listas"] and partes[2].isdigit() and partes[3] == "usos":
        id_lista = int(partes[2])
        return lambda qs, f: (contexto.servicio().editor.usos(id_lista), time.time())
    if len(partes) == 4 and partes[:2] == ["api", "listas"] and partes[2].isdigit() and partes[3] == "comprobantes":
        id_lista = int(partes[2])
        def comprobantes(qs, f):
            anio = (qs.get("anio") or [""])[0]
            if not anio.isdigit():
                raise PedidoInvalido("Falta el año.")
            return contexto.servicio().editor.comprobantes(id_lista, int(anio)), time.time()
        return comprobantes
    if len(partes) == 3 and partes[:2] == ["api", "base"]:
        # Para las Herramientas de otras PCs: la base de Tango solo se lee aca (solo lectura)
        from .. import base_tango
        ruta = partes[2]
        def base(qs, f):
            try:
                return base_tango.responder_remoto(ruta, qs), time.time()
            except ValueError as e:
                raise PedidoInvalido(str(e)) from None
            except base_tango.BaseNoDisponible as e:
                raise PedidoInvalido(str(e)) from None
        return base
    if partes == ["api", "comprobantes", "renglones"]:
        return lambda qs, f: (contexto.servicio().editor.renglones_comprobante((qs.get("t") or [""])[0], (qs.get("n") or [""])[0]), time.time())
    if len(partes) == 4 and partes[:2] == ["api", "remitos"] and partes[2].isdigit() and partes[3] == "renglones":
        id_remito = int(partes[2])
        def renglones_remito(qs, f):
            from .. import base_tango, remitos as rem
            try:
                return rem.renglones(id_remito), time.time()
            except base_tango.BaseNoDisponible as e:
                raise PedidoInvalido(str(e)) from None
        return renglones_remito
    if len(partes) == 4 and partes[:2] == ["api", "pedidos"] and partes[2].isdigit() and partes[3] == "remitos":
        from .. import base_tango
        id_pedido = int(partes[2])
        def remitos(qs, f):
            try:
                return base_tango.remitos_pedido(id_pedido), time.time()
            except base_tango.BaseNoDisponible as e:
                raise PedidoInvalido(str(e)) from None
        return remitos
    if len(partes) == 3 and partes[:2] == ["api", "pedidos"] and partes[2].isdigit():
        id_pedido = int(partes[2])
        return lambda qs, f: (contexto.servicio().gestion_pedidos.detalle(id_pedido), time.time())
    if len(partes) == 4 and partes[:2] == ["api", "cotizaciones"] and partes[3] == "renglones":
        numero = urllib.parse.unquote(partes[2]).strip()
        def renglones(qs, f):
            todos, momento = contexto.servicio().renglones_cotizaciones(f)
            return [r for r in todos if r.numero.strip() == numero], momento
        return renglones
    if len(partes) == 4 and partes[:2] == ["api", "clientes"] and partes[2].isdigit() and partes[3] == "envio":
        id_cliente = int(partes[2])
        return lambda qs, f: (contexto.servicio().datos_envio(id_cliente), time.time())
    if len(partes) == 4 and partes[:2] == ["api", "articulos"] and partes[3] == "movimientos":
        from .. import base_tango
        codigo = urllib.parse.unquote(partes[2]).strip()
        def movimientos(qs, f):
            try:
                return base_tango.movimientos_articulo(codigo), time.time()
            except (ValueError, base_tango.BaseNoDisponible) as e:
                raise PedidoInvalido(str(e)) from None
        return movimientos
    if len(partes) == 4 and partes[:2] == ["api", "articulos"] and partes[3] == "cotizaciones":
        codigo = urllib.parse.unquote(partes[2]).strip()
        return lambda qs, f: cotizaciones_de_articulo(contexto.servicio(), codigo, f)
    if len(partes) == 4 and partes[:2] == ["api", "articulos"] and partes[3] == "precios":
        codigo = urllib.parse.unquote(partes[2])
        return lambda qs, f: (contexto.servicio().editor.precios_de_articulo(codigo), time.time())
    return None


def cotizaciones_de_articulo(servicio, codigo: str, forzar: bool = False):
    """Cotizaciones en las que aparece un articulo, de la mas nueva a la mas vieja.
    Usa las mismas consultas (y la misma cache) que la pantalla de Cotizaciones."""
    renglones, momento = servicio.renglones_cotizaciones(forzar)
    cotizaciones, _ = servicio.cotizaciones(forzar)
    por_numero = {c.numero.strip(): c for c in cotizaciones}
    salida = []
    for r in renglones:
        if r.codigo_articulo.strip() != codigo:
            continue
        c = por_numero.get(r.numero.strip())
        if c is None:
            continue
        salida.append({**asdict(c), "cantidad": r.cantidad, "precio": r.precio, "descuento": r.descuento})
    salida.sort(key=lambda x: (x["fecha"] or "", x["numero"]), reverse=True)
    return salida, momento


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
        # Pedido a mano desde el panel: si hay version nueva se instala aunque la automatica este apagada
        threading.Thread(target=contexto.actualizador.revisar, kwargs={"instalar": True}, daemon=True).start()
        return 200, {"ok": True, "mensaje": "Buscando actualizaciones..."}

    def accion_accesos(datos: dict) -> tuple[int, dict]:
        try:
            lugares = sistema.crear_accesos_directos()
        except Exception as e:
            return 400, {"ok": False, "mensaje": f"No se pudieron crear: {e}"}
        if not lugares:
            return 400, {"ok": False, "mensaje": "Solo disponible con el programa instalado en Windows."}
        return 200, {"ok": True, "mensaje": "Listo: hay un acceso directo en el escritorio y en el menú Inicio."}

    def accion_modo_servidor(datos: dict) -> tuple[int, dict]:
        if datos.get("activo"):
            ok, mensaje = contexto.activar_modo_servidor()
        else:
            ok, mensaje = contexto.desactivar_modo_servidor()
        return (200 if ok else 400), {"ok": ok, "mensaje": mensaje, "sistema": contexto.info()}

    def accion_cerrar(datos: dict) -> tuple[int, dict]:
        threading.Timer(0.5, contexto.al_cerrar).start()
        return 200, {"ok": True, "mensaje": "El programa se está cerrando."}

    acciones = {
        "/api/sistema/configurar": accion_configurar,
        "/api/sistema/probar": accion_probar,
        "/api/sistema/inicio-automatico": accion_inicio,
        "/api/sistema/buscar-actualizacion": accion_actualizacion,
        "/api/sistema/accesos-directos": accion_accesos,
        "/api/sistema/modo-servidor": accion_modo_servidor,
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
            # Tipos fijos: en Windows mimetypes lee el registro, que a veces dice text/plain
            # para .js; con nosniff el navegador no correria el script.
            tipo = TIPOS.get(archivo.suffix.lower()) or mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
            if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
                tipo += "; charset=utf-8"
            self._responder(200, tipo, archivo.read_bytes())

        def _acceso_directo(self) -> None:
            """Archivo .url: al abrirlo en otra PC de Windows abre el menu en el navegador.
            Usa el nombre de esta PC (no la IP), que sigue andando aunque la IP cambie."""
            base = f"http://{sistema.nombre_equipo()}:{contexto.cfg.puerto}"
            texto = f"[InternetShortcut]\r\nURL={base}/\r\nIconFile={base}/icono.ico\r\nIconIndex=0\r\n"
            self._responder(200, "application/octet-stream", texto.encode("ascii", "replace"),
                            {"Content-Disposition": 'attachment; filename="Herramienta Sianco.url"'})

        # --------------------------------------------------------- GET
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(url.query)
            try:
                if url.path == "/api/estado":
                    act = contexto.actualizador.estado.como_dict() if contexto.actualizador else None
                    self._json(200, {"ok": True, "version": VERSION, "configurado": contexto.configurado,
                                     "tango": contexto.estado_tango.get("estado"), "actualizacion": act})
                elif url.path == "/api/sistema":
                    if not self._es_local():
                        self._json(403, {"ok": False, "error": "Solo desde la PC donde está instalado el programa."})
                    else:
                        self._json(200, {"ok": True, **contexto.info()})
                elif url.path in rutas or ruta_variable(contexto, url.path):
                    forzar = qs.get("refrescar") == ["1"]
                    datos, momento = (rutas.get(url.path) or ruta_variable(contexto, url.path))(qs, forzar)
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
                    if url.query and ("q" in qs or "art" in qs):
                        # Links viejos (Buscar estaba en el inicio): /?q=... -> /buscar?q=...
                        self._responder(302, "text/plain; charset=utf-8", b"", {"Location": "/buscar?" + url.query})
                    else:
                        self._estatico("inicio.html")
                elif url.path == "/acceso-directo.url":
                    self._acceso_directo()
                elif url.path.startswith("/cotizacion/") and url.path.endswith(".pdf"):
                    id_texto = url.path[len("/cotizacion/"):-4]
                    if not id_texto.isdigit():
                        raise PedidoInvalido("Número de cotización inválido.")
                    nombre, contenido = contexto.servicio().pdf_cotizacion(int(id_texto))
                    nombre = nombre.replace('"', "").encode("ascii", "replace").decode()
                    self._responder(200, "application/pdf", contenido,
                                    {"Content-Disposition": f'inline; filename="{nombre}"'})
                elif url.path == "/mezclas/planilla.xlsx":
                    try:
                        ids = [int(x) for x in (qs.get("ids") or [""])[0].split(",") if x.strip()]
                    except ValueError:
                        raise PedidoInvalido("Mezclas inválidas.") from None
                    nombre, contenido = contexto.servicio().mezclas.planilla(ids)
                    self._responder(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", contenido,
                                    {"Content-Disposition": f'attachment; filename="{nombre}"'})
                elif url.path == "/valorizacion.xlsx":
                    from .. import base_tango, valorizacion
                    try:
                        datos = base_tango.valorizacion_datos(False)
                    except base_tango.BaseNoDisponible as e:
                        raise PedidoInvalido(str(e)) from None
                    hoy = time.strftime("%d-%m-%Y")
                    contenido = valorizacion.excel(datos, datos.get("calculado") or hoy)
                    self._responder(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", contenido,
                                    {"Content-Disposition": f'attachment; filename="Valorizacion stock {hoy}.xlsx"'})
                elif url.path == "/icono.ico":
                    icono = ruta_recurso("recursos/icono.ico")
                    if icono.is_file():
                        self._responder(200, "image/x-icon", icono.read_bytes())
                    else:
                        self._responder(404, "text/plain; charset=utf-8", "No encontrado".encode())
                else:
                    relativa = url.path.strip("/")
                    if "." not in relativa.rsplit("/", 1)[-1]:
                        relativa += ".html"   # /stock -> stock.html
                    self._estatico(relativa)
            except (PedidoInvalido, DatoInvalido) as e:
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
        def _leer_cuerpo(self, maximo: int = MAX_CUERPO) -> dict | None:
            try:
                largo = int(self.headers.get("Content-Length") or 0)
                if largo > maximo:
                    self._json(413, {"ok": False, "error": "Pedido demasiado grande."})
                    return None
                cuerpo = self.rfile.read(largo) if largo else b"{}"
                datos = json.loads(cuerpo.decode("utf-8") or "{}")
                if not isinstance(datos, dict):
                    raise ValueError
                return datos
            except (ValueError, UnicodeDecodeError):
                self._json(400, {"ok": False, "error": "Pedido inválido."})
                return None

        def _quien(self) -> str:
            """Nombre que mando la pagina (lo recuerda cada equipo) y la IP, para el registro."""
            nombre = urllib.parse.unquote(self.headers.get(ENCABEZADO_NOMBRE) or "")
            nombre = " ".join(nombre.split())[:40]
            return f"{nombre} ({self.client_address[0]})" if nombre else self.client_address[0]

        def _post_app(self, ruta: str) -> None:
            datos = self._leer_cuerpo(MAX_CUERPO_ARCHIVO if ruta == "/api/listas/importar/analizar" else MAX_CUERPO)
            if datos is None:
                return
            texto = lambda clave: str(datos.get(clave) or "")
            entero = lambda clave: int(datos[clave]) if datos.get(clave) not in (None, "") else None
            quien = self._quien()
            try:
                editor = contexto.servicio().editor
                if ruta == "/api/precios/cambiar":
                    r = editor.cambiar_precio(entero("renglon"), datos.get("precio"), quien, entero("cliente"))
                elif ruta == "/api/precios/agregar":
                    r = editor.agregar_articulo(entero("lista"), texto("articulo"), datos.get("precio"),
                                                quien, entero("cliente"), texto("codigo_cliente"))
                elif ruta == "/api/precios/quitar":
                    r = editor.quitar_articulo(entero("renglon"), quien)
                elif ruta == "/api/listas/crear":
                    r = editor.crear_lista(texto("nombre"), texto("moneda"), quien, entero("numero"), entero("cliente"))
                elif ruta == "/api/listas/asignar":
                    r = editor.asignar_lista(entero("lista"), entero("cliente"), quien)
                elif ruta == "/api/pedidos/eliminar":
                    if not opciones.leer()["pedidos_eliminar"]:
                        raise DatoInvalido("Eliminar pedidos desde la Herramienta está desactivado: la licencia de Tango "
                                           "no lo permite. Hacelo desde la pantalla de Pedidos de Tango.")
                    r = contexto.servicio().gestion_pedidos.eliminar(entero("id"), texto("confirmar"), quien)
                elif ruta == "/api/opciones":
                    try:
                        r = opciones.cambiar(texto("clave"), datos.get("valor"))
                    except ValueError as e:
                        raise DatoInvalido(str(e)) from None
                    log.info(f"Opciones: {quien} cambió {texto('clave')} a {datos.get('valor')}")
                elif ruta == "/api/listas/restaurar":
                    r = editor.restaurar_lista(texto("fecha"), texto("lista"), quien)
                elif ruta == "/api/precios/ajuste/vista-previa":
                    r = editor.vista_previa_ajuste(datos.get("porcentaje"), entero("lista"), datos.get("articulos"))
                elif ruta == "/api/precios/ajuste":
                    r = editor.ajustar_precios(datos.get("porcentaje"), quien, entero("lista"), datos.get("articulos"))
                elif ruta == "/api/precios/ajuste/revertir":
                    r = editor.revertir_ajuste(texto("fecha"), quien)
                elif ruta == "/api/listas/importar/analizar":
                    try:
                        contenido = base64.b64decode(texto("archivo"), validate=True)
                    except (binascii.Error, ValueError):
                        raise DatoInvalido("No se pudo leer el archivo.") from None
                    r = contexto.servicio().importador.analizar(contenido)
                elif ruta == "/api/listas/importar/aplicar":
                    r = contexto.servicio().importador.aplicar(texto("plan"), quien, bool(datos.get("actualizar_distintos")),
                                                               bool(datos.get("saltear_observaciones")))
                elif ruta == "/api/mezclas/crear":
                    r = contexto.servicio().mezclas.crear(texto("referencia"), datos.get("renglones"), quien)
                elif ruta == "/api/mezclas/subidas":
                    r = contexto.servicio().mezclas.marcar_subidas([int(x) for x in datos.get("ids") or []], quien)
                elif ruta == "/api/mezclas/borrar":
                    contexto.servicio().mezclas.borrar(entero("id"), quien); r = None
                else:
                    r = editor.eliminar_lista(entero("lista"), texto("confirmar"), quien, entero("reasignar_a"))
                self._json(200, {"ok": True, "datos": r})
            except DatoInvalido as e:
                self._json(400, {"ok": False, "error": str(e)})
            except (KeyError, TypeError, ValueError):
                self._json(400, {"ok": False, "error": "Faltan datos en el pedido."})
            except NoConfigurado as e:
                self._json(503, {"ok": False, "error": str(e)})
            except TangoError as e:
                log.error(f"Precios: {e}")
                self._json(502, {"ok": False, "error": str(e)})
            except Exception as e:
                log.exception("Error al modificar")
                self._json(500, {"ok": False, "error": f"Error inesperado: {e.__class__.__name__}"})

        def _exportar(self) -> None:
            """Arma un .xlsx con lo que manda la pagina (lo que se ve en pantalla). No toca Tango."""
            from .. import xlsx
            datos = self._leer_cuerpo(MAX_CUERPO_ARCHIVO)
            if datos is None:
                return
            try:
                columnas = [(str(c["titulo"])[:80], "numero" if c.get("tipo") == "numero" else "texto")
                            for c in datos["columnas"]][:MAX_COLUMNAS_EXPORTAR]
                filas = datos["filas"]
                if not columnas or not isinstance(filas, list) or not all(isinstance(f, list) for f in filas):
                    raise ValueError
                contenido = xlsx.escribir(columnas, filas, str(datos.get("nombre") or "Datos"))
            except ValueError as e:
                self._json(400, {"ok": False, "error": str(e) or "Datos inválidos para exportar."})
                return
            except (KeyError, TypeError):
                self._json(400, {"ok": False, "error": "Datos inválidos para exportar."})
                return
            nombre = " ".join(str(datos.get("nombre") or "Herramienta Sianco").split())[:80]
            ascii_ = nombre.encode("ascii", "replace").decode().replace('"', "").replace("?", "_")
            self._responder(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", contenido,
                            {"Content-Disposition": f'attachment; filename="{ascii_}.xlsx"; filename*=UTF-8\'\'{urllib.parse.quote(nombre)}.xlsx'})

        def _comparar_inventario(self) -> None:
            """Compara el Excel de inventario con el stock de Tango. Solo lee."""
            from .. import inventario
            datos = self._leer_cuerpo(MAX_CUERPO_INVENTARIO)
            if datos is None:
                return
            try:
                contenido = base64.b64decode(str(datos.get("archivo") or ""), validate=True)
                if not contenido:
                    raise ValueError
            except (binascii.Error, ValueError):
                self._json(400, {"ok": False, "error": "No se pudo leer el archivo."})
                return
            try:
                r = inventario.comparar(contenido, contexto.servicio(), str(datos.get("nombre") or "")[:120])
            except inventario.InventarioInvalido as e:
                self._json(400, {"ok": False, "error": str(e)})
                return
            except NoConfigurado as e:
                self._json(503, {"ok": False, "error": str(e)})
                return
            except TangoError as e:
                self._json(502, {"ok": False, "error": str(e)})
                return
            except Exception as e:
                log.exception("Error al comparar el inventario")
                self._json(500, {"ok": False, "error": f"Error inesperado: {e.__class__.__name__}"})
                return
            distintas = [f for f in r["filas"] if f["estado"] != "Coincide"]
            self._json(200, {"ok": True, "datos": {
                "resumen": r["resumen"], "filas": distintas[:MAX_FILAS_RESPUESTA], "total_distintas": len(distintas),
                "archivo": base64.b64encode(r["archivo"]).decode("ascii")}})

        def do_POST(self):
            url = urllib.parse.urlparse(self.path)
            if url.path == "/api/inventario/comparar":
                self._comparar_inventario()
                return
            if url.path == "/api/exportar":
                self._exportar()
                return
            if url.path in RUTAS_APP:
                self._post_app(url.path)
                return
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
            datos = self._leer_cuerpo()
            if datos is None:
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
