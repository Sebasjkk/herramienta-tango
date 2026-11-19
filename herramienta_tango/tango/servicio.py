"""
Servicio Tango: la puerta unica de la herramienta hacia Tango.

Todo lo que se construya encima (la pagina de stock, futuros modulos,
informes) pide los datos a esta clase y recibe modelos con nombres claros.
Nadie mas llama al cliente HTTP ni conoce los nombres internos de Tango.

Incluye una cache por consulta, para no pedirle lo mismo a Tango en cada
busqueda desde el celular.
"""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Callable, TypeVar

from . import procesos
from .cliente import ClienteTango, TangoError
from .modelos import (Articulo, Cliente, Cotizacion, DatosEnvio, Deposito, ListaPrecios, Pedido,
                      PrecioVigente, Remito, RenglonCotizacion, RenglonVenta, SaldoArticulo, SaldoPartida, solo_digitos)

T = TypeVar("T")


class _Cache:
    def __init__(self):
        self._datos: dict[str, tuple[float, object]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock_global = threading.Lock()

    def _lock(self, clave: str) -> threading.Lock:
        with self._lock_global:
            return self._locks.setdefault(clave, threading.Lock())

    def obtener(self, clave: str, segundos: int, cargar: Callable[[], T], forzar: bool = False) -> tuple[T, float]:
        """Devuelve (datos, momento_de_carga). Un solo pedido a Tango por clave a la vez."""
        with self._lock(clave):
            guardado = self._datos.get(clave)
            if guardado and not forzar and time.time() - guardado[0] < segundos:
                return guardado[1], guardado[0]  # type: ignore[return-value]
            datos = cargar()
            momento = time.time()
            self._datos[clave] = (momento, datos)
            return datos, momento

    def olvidar(self, clave: str) -> None:
        with self._lock_global:
            self._datos.pop(clave, None)


class ServicioTango:
    # Segundos que se reutiliza cada consulta
    VIGENCIA = {
        "saldos_partida": 60,
        "pedidos": 60,
        "ventas": 60,
        "articulos": 600,
        "clientes": 600,
        "listas_precios": 600,
        "precios": 300,
        "cotizaciones": 60,
        "remitos": 60,
        "depositos": 3600,
    }

    def __init__(self, cliente: ClienteTango, vigencia_saldos: int | None = None):
        self._cliente = cliente
        self._cache = _Cache()
        self.vigencia = dict(self.VIGENCIA)
        if vigencia_saldos is not None:
            self.vigencia["saldos_partida"] = vigencia_saldos

    def olvidar(self, clave: str) -> None:
        """Descarta lo guardado de una consulta (despues de modificar datos en Tango)."""
        self._cache.olvidar(clave)

    @property
    def editor(self):
        """Editor de listas de precios (lee y escribe en Tango). Se arma la primera vez que se usa."""
        if getattr(self, "_editor", None) is None:
            from ..precios import EditorPrecios
            self._editor = EditorPrecios(self._cliente, self)
        return self._editor

    @property
    def importador(self):
        """Importacion de listas de precios desde Excel."""
        if getattr(self, "_importador", None) is None:
            from ..importar_listas import ImportadorListas
            self._importador = ImportadorListas(self.editor, self)
        return self._importador

    @property
    def mezclas(self):
        """Mezclas de polvos: historial y planilla de egreso para Tango."""
        if getattr(self, "_mezclas", None) is None:
            from ..mezclas import EditorMezclas
            self._mezclas = EditorMezclas(self)
        return self._mezclas

    def _cacheado(self, clave: str, tipo: str, cargar: Callable[[], T], forzar: bool) -> tuple[T, float]:
        return self._cache.obtener(clave, self.vigencia[tipo], cargar, forzar)

    # --------------------------------------------------------------- stock
    def saldos_por_partida(self, forzar: bool = False) -> tuple[list[SaldoPartida], float]:
        return self._cacheado("saldos_partida", "saldos_partida", lambda: [
            SaldoPartida.desde_tango(x)
            for x in self._cliente.consulta_live(procesos.LIVE_SALDOS_POR_PARTIDA)
        ], forzar)

    def saldos_por_articulo(self, forzar: bool = False) -> tuple[list[SaldoArticulo], float]:
        """Saldo por articulo y deposito: sirve para los articulos que no llevan partidas."""
        return self._cacheado("saldos_articulo", "saldos_partida", lambda: [
            SaldoArticulo.desde_tango(x)
            for x in self._cliente.consulta_live(procesos.LIVE_SALDOS_POR_ARTICULO)
        ], forzar)

    def articulos(self, forzar: bool = False) -> tuple[list[Articulo], float]:
        return self._cacheado("articulos", "articulos", lambda: [
            Articulo.desde_tango(x) for x in self._cliente.listar(procesos.ARTICULOS)
        ], forzar)

    def depositos(self, forzar: bool = False) -> tuple[list[Deposito], float]:
        return self._cacheado("depositos", "depositos", lambda: [
            Deposito.desde_tango(x) for x in self._cliente.listar(procesos.DEPOSITOS)
        ], forzar)

    # --------------------------------------------------------------- ventas
    def clientes(self, forzar: bool = False) -> tuple[list[Cliente], float]:
        return self._cacheado("clientes", "clientes", lambda: [
            Cliente.desde_tango(x) for x in self._cliente.listar(procesos.CLIENTES)
        ], forzar)

    def pedidos(self, forzar: bool = False) -> tuple[list[Pedido], float]:
        return self._cacheado("pedidos", "pedidos", lambda: [
            Pedido.desde_tango(x) for x in self._cliente.listar(procesos.PEDIDOS)
        ], forzar)

    def listas_precios(self, forzar: bool = False) -> tuple[list[ListaPrecios], float]:
        return self._cacheado("listas_precios", "listas_precios", lambda: [
            ListaPrecios.desde_tango(x) for x in self._cliente.listar(procesos.LISTAS_PRECIOS)
        ], forzar)

    def precios(self, forzar: bool = False) -> tuple[list[PrecioVigente], float]:
        """Precios vigentes de todas las listas (consulta Live 12742)."""
        return self._cacheado("precios", "precios", lambda: [
            PrecioVigente.desde_tango(x)
            for x in self._cliente.consulta_live(procesos.LIVE_PRECIOS_VIGENTES)
        ], forzar)

    # --------------------------------------------------------------- cotizaciones
    DESDE_SIEMPRE = date(2000, 1, 1)

    def cotizaciones(self, forzar: bool = False) -> tuple[list[Cotizacion], float]:
        return self._cacheado("cotizaciones", "cotizaciones", lambda: [
            Cotizacion.desde_tango(x)
            for x in self._cliente.consulta_live(procesos.LIVE_COTIZACIONES, self.DESDE_SIEMPRE, date.today())
        ], forzar)

    def renglones_cotizaciones(self, forzar: bool = False) -> tuple[list[RenglonCotizacion], float]:
        return self._cacheado("renglones_cotizaciones", "cotizaciones", lambda: [
            RenglonCotizacion.desde_tango(x)
            for x in self._cliente.consulta_live(procesos.LIVE_COTIZACIONES_DETALLE, self.DESDE_SIEMPRE, date.today())
        ], forzar)

    def pdf_cotizacion(self, id_cotizacion: int) -> tuple[str, bytes]:
        return self._cliente.pdf(procesos.TABLERO_FICHA_COTIZACION, id_cotizacion)

    # --------------------------------------------------------------- remitos y etiquetas
    def remitos(self, forzar: bool = False) -> tuple[list[Remito], float]:
        """Remitos del ultimo año, con la OC del pedido que los referencia (si hay)."""
        from dataclasses import replace
        from datetime import timedelta

        def cargar():
            filas = self._cliente.consulta_live(procesos.LIVE_COMPROBANTES_VENTA, date.today() - timedelta(days=365), date.today())
            remitos = [Remito.desde_tango(x) for x in filas if str(x.get("TIPO_COMPROBANTE") or "").strip().upper() == "REM"]
            try:
                pedidos, _ = self.pedidos(forzar)
            except Exception:
                pedidos = []
            por_remito = {}
            for p in pedidos:
                d = solo_digitos(p.numero_remito)
                if d and int(d):
                    por_remito[d.lstrip("0")] = p
            salida = []
            for r in remitos:
                p = por_remito.get(solo_digitos(r.numero).lstrip("0"))
                salida.append(replace(r, orden_compra=p.orden_compra_cliente, pedido=p.numero) if p else r)
            salida.sort(key=lambda r: (r.fecha or "", r.numero), reverse=True)
            return salida
        return self._cacheado("remitos", "remitos", cargar, forzar)

    def datos_envio(self, id_cliente: int) -> DatosEnvio:
        x = self._cliente.obtener(procesos.CLIENTES, id_cliente)
        if not x:
            raise TangoError("No se encontró el cliente en Tango.")
        return DatosEnvio.desde_tango(x)

    def ventas(self, desde: date, hasta: date, forzar: bool = False) -> tuple[list[RenglonVenta], float]:
        clave = f"ventas:{desde.isoformat()}:{hasta.isoformat()}"
        return self._cacheado(clave, "ventas", lambda: [
            RenglonVenta.desde_tango(x)
            for x in self._cliente.consulta_live(procesos.LIVE_VENTAS_DETALLE, desde, hasta)
        ], forzar)
