"""
Editor de listas de precios: lee y modifica las listas, sus articulos y los
precios especiales por cliente, directo en las tablas de Tango.

Como guarda Tango los precios (verificado el 17/11/2026):
- Lista de precios: GVA10, proceso 984.
- Articulo dentro de una lista: GVA17, proceso 20091. Tiene el precio de lista.
- Precio especial de un cliente para ese articulo en esa lista: GVA13, que
  viene adentro del renglon de GVA17 (campo GVA13) y se graba con el mismo
  Update. Las listas de cliente (SCIPIO, TECSPRAY...) tienen el precio de
  lista en 0 y el precio real como precio especial del cliente.

La consulta "Precios vigentes a una fecha" (12742) NO sirve para editar: lee
un historial y no muestra lo que se carga por la API. Aca se lee siempre de
las tablas.

Cada escritura se verifica volviendo a leer el registro, y queda anotada en
cambios_precios.jsonl (quien, cuando, antes y despues).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from . import config
from .tango import TangoError, procesos
from .tango.modelos import ListaPrecios, RenglonPrecio

log = logging.getLogger("herramienta_tango")

PROCESO_LISTAS = procesos.LISTAS_PRECIOS     # 984
PROCESO_RENGLONES = procesos.PRECIOS_ABM     # 20091
LIMITE_DETALLE = 400        # listas con hasta tantos articulos se leen con los precios especiales
VIGENCIA_RENGLONES = 60     # segundos
MAX_NOMBRE_LISTA = 20


class PedidoInvalido(ValueError):
    """Datos mal cargados: el mensaje se muestra tal cual."""


# ------------------------------------------------------------------ registro
class RegistroCambios:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        self._lock = threading.Lock()

    def anotar(self, quien: str, accion: str, **datos) -> None:
        entrada = {"fecha": datetime.now().isoformat(timespec="seconds"), "quien": quien, "accion": accion, **datos}
        with self._lock, open(self.ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
        log.info(f"Precios: {quien} - {accion} - {json.dumps(datos, ensure_ascii=False)[:300]}")

    def ultimos(self, cantidad: int = 200) -> list[dict]:
        if not self.ruta.exists():
            return []
        with self._lock:
            lineas = self.ruta.read_text(encoding="utf-8").splitlines()[-cantidad:]
        salida = []
        for l in reversed(lineas):
            try:
                salida.append(json.loads(l))
            except json.JSONDecodeError:
                pass
        return salida


def ruta_registro() -> Path:
    return config.CARPETA / "cambios_precios.jsonl"


# ------------------------------------------------------------------ utilidades
def _precio(valor, decimales: int = 2) -> float:
    try:
        numero = round(float(str(valor).replace(",", ".")), decimales)
    except (TypeError, ValueError):
        raise PedidoInvalido("El precio tiene que ser un número.") from None
    if numero < 0 or numero > 1e10:
        raise PedidoInvalido("El precio no puede ser negativo.")
    return numero


def _resumen(r: dict) -> dict:
    return {"precio": r.get("PRECIO"),
            "especiales": [{"cliente": c.get("COD_CLIENT"), "precio": c.get("PRECIO")} for c in (r.get("GVA13") or [])]}


class EditorPrecios:
    def __init__(self, cliente, servicio, registro: RegistroCambios | None = None):
        self._c = cliente
        self._servicio = servicio            # para clientes y articulos
        self.registro = registro or RegistroCambios(ruta_registro())
        self._lock = threading.Lock()        # una escritura a la vez
        self._renglones: tuple[float, list[dict]] | None = None

    # ============================================================== lecturas
    def _todos_los_renglones(self, forzar: bool = False) -> list[dict]:
        if forzar or not self._renglones or time.time() - self._renglones[0] > VIGENCIA_RENGLONES:
            self._renglones = (time.time(), self._c.listar(PROCESO_RENGLONES))
        return self._renglones[1]

    def _invalidar(self) -> None:
        self._renglones = None
        self._servicio.olvidar("precios")

    def _listas_crudas(self) -> list[dict]:
        return self._c.listar(PROCESO_LISTAS)

    def _clientes_por_codigo(self) -> dict:
        try:
            clientes, _ = self._servicio.clientes()
        except TangoError:
            return {}
        return {c.codigo: c for c in clientes}

    def listas(self, forzar: bool = False) -> list[dict]:
        """Las listas con cuantos articulos tienen y que clientes la tienen asignada."""
        renglones = self._todos_los_renglones(forzar)
        cantidad = Counter(r.get("ID_GVA10") for r in renglones)
        con_precio = Counter(r.get("ID_GVA10") for r in renglones if (r.get("PRECIO") or 0) > 0)
        asignada: dict[str, list[str]] = {}
        try:
            clientes, _ = self._servicio.clientes(forzar)
            for c in clientes:
                if c.lista_precios:
                    asignada.setdefault(c.lista_precios.strip().upper(), []).append(c.razon_social)
        except TangoError:
            pass
        salida = []
        for x in self._listas_crudas():
            l = ListaPrecios.desde_tango(x)
            salida.append({
                **asdict(l),
                "nombre": l.nombre or f"Lista {l.numero}",
                "moneda": "$" if l.moneda_corriente else "US$",
                "articulos": cantidad.get(l.id, 0),
                "con_precio_de_lista": con_precio.get(l.id, 0),
                "clientes_asignados": sorted(asignada.get((l.nombre or "").strip().upper(), [])),
            })
        salida.sort(key=lambda d: d["numero"] or 0)
        return salida

    def _lista(self, id_lista: int) -> dict:
        x = self._c.obtener(PROCESO_LISTAS, id_lista)
        if not x:
            raise PedidoInvalido("Esa lista ya no existe en Tango.")
        return x

    def _detalles(self, ids: list[int]) -> dict[int, dict]:
        with ThreadPoolExecutor(max_workers=8) as ex:
            return {i: d for i, d in zip(ids, ex.map(lambda i: self._c.obtener(PROCESO_RENGLONES, i), ids)) if d}

    def lista(self, id_lista: int, forzar: bool = False) -> dict:
        """Una lista con todos sus articulos y, si no es enorme, los precios especiales."""
        cruda = self._lista(id_lista)
        l = ListaPrecios.desde_tango(cruda)
        filas = [r for r in self._todos_los_renglones(forzar) if r.get("ID_GVA10") == id_lista]
        detalles = self._detalles([r["ID_GVA17"] for r in filas]) if len(filas) <= LIMITE_DETALLE else {}
        renglones = [RenglonPrecio.desde_tango(r, detalles.get(r["ID_GVA17"]) if detalles else None) for r in filas]
        renglones.sort(key=lambda r: (r.descripcion, r.codigo_articulo))
        dueno = self._dueno(renglones)
        clientes = self._clientes_por_codigo()
        return {
            "lista": {**asdict(l), "nombre": l.nombre or f"Lista {l.numero}", "moneda": "$" if l.moneda_corriente else "US$",
                      "decimales": cruda.get("DECIMALES") or 2},
            "cliente": dueno and {**dueno, "razon_social": getattr(clientes.get(dueno["codigo"]), "razon_social", "")},
            "especiales_leidos": bool(detalles) or not filas,
            "renglones": [asdict(r) for r in renglones],
        }

    @staticmethod
    def _dueno(renglones: list[RenglonPrecio]) -> dict | None:
        """El cliente de una lista de cliente: el que tiene precios especiales en la mayoria de sus articulos."""
        cuenta = Counter((e.id_cliente, e.codigo_cliente) for r in renglones for e in (r.especiales or ()))
        if not cuenta:
            return None
        (id_cliente, codigo), _ = cuenta.most_common(1)[0]
        return {"id": id_cliente, "codigo": codigo}

    def precios_de_articulo(self, codigo: str) -> list[dict]:
        """En que listas esta un articulo, con su precio de lista y los especiales."""
        filas = [r for r in self._todos_los_renglones() if (r.get("COD_STA11") or "").strip() == codigo.strip()]
        detalles = self._detalles([r["ID_GVA17"] for r in filas])
        clientes = self._clientes_por_codigo()
        salida = []
        for r in filas:
            renglon = RenglonPrecio.desde_tango(r, detalles.get(r["ID_GVA17"]))
            salida.append({
                **asdict(renglon),
                "lista": (r.get("NOMBRE_LIS") or "").strip() or f"Lista {r.get('NRO_DE_LIS')}",
                "moneda": "$" if "PESO" in (r.get("MONEDA_CORRIENTE") or "").upper() else "US$",
                "especiales": [{**asdict(e), "razon_social": getattr(clientes.get(e.codigo_cliente), "razon_social", "")}
                               for e in (renglon.especiales or ())],
            })
        salida.sort(key=lambda d: d["lista"])
        return salida

    # ============================================================== escrituras
    def _leer_renglon(self, id_renglon: int) -> dict:
        r = self._c.obtener(PROCESO_RENGLONES, id_renglon)
        if not r:
            raise PedidoInvalido("Ese artículo ya no está en la lista (puede que alguien lo haya quitado).")
        return r

    def cambiar_precio(self, id_renglon: int, precio, quien: str, id_cliente: int | None = None) -> dict:
        """Cambia el precio de lista, o el precio especial de un cliente si se indica id_cliente."""
        with self._lock:
            actual = self._leer_renglon(id_renglon)
            lista = self._lista(actual["ID_GVA10"])
            nuevo_precio = _precio(precio, lista.get("DECIMALES") or 2)
            antes = _resumen(actual)
            nuevo = dict(actual)
            if id_cliente is None:
                nuevo["PRECIO"] = nuevo_precio
            else:
                especiales = [dict(c) for c in (actual.get("GVA13") or [])]
                cambiado = [c for c in especiales if c.get("ID_GVA14") == id_cliente]
                if not cambiado:
                    raise PedidoInvalido("Ese cliente no tiene precio especial en este artículo.")
                for c in cambiado:
                    c["PRECIO"] = nuevo_precio
                nuevo["GVA13"] = especiales
            self._c.actualizar(PROCESO_RENGLONES, nuevo)
            despues_crudo = self._leer_renglon(id_renglon)
            despues = _resumen(despues_crudo)
            ok = (despues_crudo.get("PRECIO") == nuevo_precio if id_cliente is None else
                  any(c.get("ID_GVA14") == id_cliente and c.get("PRECIO") == nuevo_precio for c in despues_crudo.get("GVA13") or []))
            self._invalidar()
            self.registro.anotar(quien, "cambiar precio", lista=lista.get("NOMBRE_LIS"), articulo=actual.get("COD_ARTICU"),
                                 cliente=id_cliente, antes=antes, despues=despues)
            if not ok:
                raise TangoError("Tango aceptó el cambio pero el precio guardado no coincide. Revisalo en Tango.")
            return {"antes": antes, "despues": despues}

    def agregar_articulo(self, id_lista: int, codigo_articulo: str, precio, quien: str,
                         id_cliente: int | None = None, codigo_cliente: str = "") -> dict:
        """Agrega un articulo a una lista. Si la lista es de un cliente (o se indica uno), el precio
        va como precio especial de ese cliente y el de lista queda en 0, como el resto de esas listas."""
        with self._lock:
            lista = self._lista(id_lista)
            nuevo_precio = _precio(precio, lista.get("DECIMALES") or 2)
            codigo_articulo = (codigo_articulo or "").strip()
            articulos, _ = self._servicio.articulos()
            art = next((a for a in articulos if a.codigo == codigo_articulo), None)
            if not art:
                raise PedidoInvalido(f"No existe el artículo {codigo_articulo} en Tango.")
            filas = [r for r in self._todos_los_renglones(forzar=True) if r.get("ID_GVA10") == id_lista]
            if any((r.get("COD_STA11") or "").strip() == codigo_articulo for r in filas):
                raise PedidoInvalido("Ese artículo ya está en la lista: cambiale el precio.")
            if id_cliente is None:
                detalles = self._detalles([r["ID_GVA17"] for r in filas[:20]])   # alcanza con una muestra
                dueno = self._dueno([RenglonPrecio.desde_tango(r, detalles.get(r["ID_GVA17"])) for r in filas
                                     if r["ID_GVA17"] in detalles])
                if dueno:
                    id_cliente, codigo_cliente = dueno["id"], dueno["codigo"]
            registro = {
                "ID_STA11": art.id, "DECIMALES_RESTO": None, "DECIMALES_GVA17": lista.get("DECIMALES") or 2,
                "NRO_DE_LIS": lista.get("NRO_DE_LIS"), "COD_ARTICU": art.codigo, "ID_GVA10": id_lista,
                "PRECIO": 0 if id_cliente is not None else nuevo_precio, "BASE": False, "FILLER": "", "GVA13": [],
            }
            nuevo_id = self._c.crear(PROCESO_RENGLONES, registro)
            if not nuevo_id:
                raise TangoError("Tango no devolvió el número del renglón nuevo.")
            if id_cliente is not None:
                creado = self._leer_renglon(nuevo_id)
                creado["GVA13"] = [{
                    "ACTUALIZAR_CONTROL_PRECIOS": False, "ID_GVA10": id_lista, "ID_STA11": art.id, "ID_GVA14": id_cliente,
                    "FILLER": "", "COD_ARTICU": art.codigo, "COD_CLIENT": codigo_cliente,
                    "NRO_LISTA": lista.get("NRO_DE_LIS"), "PRECIO": nuevo_precio, "ID_GVA17": nuevo_id,
                }]
                self._c.actualizar(PROCESO_RENGLONES, creado)
            despues = _resumen(self._leer_renglon(nuevo_id))
            self._invalidar()
            self.registro.anotar(quien, "agregar artículo", lista=lista.get("NOMBRE_LIS"), articulo=art.codigo,
                                 cliente=codigo_cliente or None, despues=despues)
            return {"id": nuevo_id, "despues": despues}

    def quitar_articulo(self, id_renglon: int, quien: str) -> dict:
        with self._lock:
            actual = self._leer_renglon(id_renglon)
            lista = self._lista(actual["ID_GVA10"])
            antes = _resumen(actual)
            self._borrar_renglon(actual)
            self._invalidar()
            self.registro.anotar(quien, "quitar artículo", lista=lista.get("NOMBRE_LIS"),
                                 articulo=actual.get("COD_ARTICU"), antes=antes)
            return {"antes": antes}

    def _borrar_renglon(self, actual: dict) -> None:
        # Primero los precios especiales: el borrado del renglon no informa si los arrastra
        if actual.get("GVA13"):
            self._c.actualizar(PROCESO_RENGLONES, {**actual, "GVA13": []})
        self._c.borrar(PROCESO_RENGLONES, actual["ID_GVA17"])
        if self._c.obtener(PROCESO_RENGLONES, actual["ID_GVA17"]):
            raise TangoError("Tango no borró el artículo de la lista.")

    def crear_lista(self, nombre: str, moneda: str, quien: str, numero: int | None = None) -> dict:
        nombre = " ".join((nombre or "").split()).upper()
        if not nombre:
            raise PedidoInvalido("Escribí el nombre de la lista.")
        if len(nombre) > MAX_NOMBRE_LISTA:
            raise PedidoInvalido(f"El nombre puede tener hasta {MAX_NOMBRE_LISTA} letras.")
        if moneda not in ("$", "US$"):
            raise PedidoInvalido("Elegí la moneda: pesos o dólares.")
        with self._lock:
            existentes = self._listas_crudas()
            if any((x.get("NOMBRE_LIS") or "").strip().upper() == nombre for x in existentes):
                raise PedidoInvalido("Ya hay una lista con ese nombre.")
            usados = {x.get("NRO_DE_LIS") for x in existentes}
            if numero is None:
                numero = max([n for n in usados if isinstance(n, int)] + [0]) + 1
            elif numero in usados:
                raise PedidoInvalido(f"Ya existe la lista número {numero}.")
            if not 1 <= int(numero) <= 9999:
                raise PedidoInvalido("El número de lista tiene que estar entre 1 y 9999.")
            modelo = self._c.obtener(PROCESO_LISTAS, existentes[0]["ID_GVA10"]) if existentes else {}
            registro = {**(modelo or {}),
                        "GVA10_PARAMETROS_AUTOMATIZACION": [], "CTA_LISTA_VENTA_POR_SUCURSAL": [],
                        "NRO_DE_LIS": int(numero), "NOMBRE_LIS": nombre, "HABILITADA": True,
                        "MON_CTE": moneda == "$", "DECIMALES": 2, "INCLUY_IVA": False, "INCLUY_IMP": False,
                        "FEC_DESDE": None, "FEC_HASTA": None, "OBSERVACIONES": None,
                        "COD_DESCRIP": f"{numero} - {nombre}"}
            registro.pop("ID_GVA10", None)
            nuevo_id = self._c.crear(PROCESO_LISTAS, registro)
            if not nuevo_id or not self._c.obtener(PROCESO_LISTAS, nuevo_id):
                raise TangoError("Tango no creó la lista.")
            self._invalidar()
            self.registro.anotar(quien, "crear lista", lista=nombre, numero=int(numero), moneda=moneda)
            return {"id": nuevo_id, "numero": int(numero), "nombre": nombre}

    def eliminar_lista(self, id_lista: int, confirmar_nombre: str, quien: str) -> dict:
        with self._lock:
            lista = self._lista(id_lista)
            nombre = (lista.get("NOMBRE_LIS") or "").strip()
            if " ".join((confirmar_nombre or "").split()).upper() != nombre.upper():
                raise PedidoInvalido("Para eliminar la lista escribí su nombre exacto.")
            clientes, _ = self._servicio.clientes(forzar=True)
            asignados = [c.razon_social for c in clientes if c.lista_precios.strip().upper() == nombre.upper()]
            if asignados:
                raise PedidoInvalido(
                    "No se puede eliminar: la tienen asignada en Tango " +
                    (asignados[0] if len(asignados) == 1 else f"{len(asignados)} clientes") +
                    ". Primero hay que cambiarles la lista en la ficha del cliente.")
            filas = [r for r in self._todos_los_renglones(forzar=True) if r.get("ID_GVA10") == id_lista]
            copia = []
            for r in filas:
                actual = self._c.obtener(PROCESO_RENGLONES, r["ID_GVA17"])
                if not actual:
                    continue
                copia.append({"articulo": actual.get("COD_ARTICU"), **_resumen(actual)})
                self._borrar_renglon(actual)
            self._c.borrar(PROCESO_LISTAS, id_lista)
            self._invalidar()
            sigue = self._c.obtener(PROCESO_LISTAS, id_lista)
            # El contenido completo queda en el registro, por si hay que volver a cargarla
            self.registro.anotar(quien, "eliminar lista", lista=nombre, numero=lista.get("NRO_DE_LIS"),
                                 articulos=len(copia), contenido=copia)
            if sigue:
                raise TangoError("Se quitaron los artículos, pero Tango no borró la lista.")
            return {"articulos_quitados": len(copia)}
