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
from .cliente import ClienteTango
from .modelos import (Articulo, Cliente, Deposito, ListaPrecios, Pedido,
                      PrecioVigente, RenglonVenta, SaldoPartida)

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
        "depositos": 3600,
    }

    def __init__(self, cliente: ClienteTango, vigencia_saldos: int | None = None):
        self._cliente = cliente
        self._cache = _Cache()
        self.vigencia = dict(self.VIGENCIA)
        if vigencia_saldos is not None:
            self.vigencia["saldos_partida"] = vigencia_saldos

    def _cacheado(self, clave: str, tipo: str, cargar: Callable[[], T], forzar: bool) -> tuple[T, float]:
        return self._cache.obtener(clave, self.vigencia[tipo], cargar, forzar)

    # --------------------------------------------------------------- stock
    def saldos_por_partida(self, forzar: bool = False) -> tuple[list[SaldoPartida], float]:
        return self._cacheado("saldos_partida", "saldos_partida", lambda: [
            SaldoPartida.desde_tango(x)
            for x in self._cliente.consulta_live(procesos.LIVE_SALDOS_POR_PARTIDA)
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

    def ventas(self, desde: date, hasta: date, forzar: bool = False) -> tuple[list[RenglonVenta], float]:
        clave = f"ventas:{desde.isoformat()}:{hasta.isoformat()}"
        return self._cacheado(clave, "ventas", lambda: [
            RenglonVenta.desde_tango(x)
            for x in self._cliente.consulta_live(procesos.LIVE_VENTAS_DETALLE, desde, hasta)
        ], forzar)
