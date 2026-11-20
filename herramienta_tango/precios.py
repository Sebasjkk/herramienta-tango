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
import re
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
PROCESO_CLIENTES = procesos.CLIENTES         # 2117 (ficha completa con GetById)
PROCESO_PEDIDOS = procesos.PEDIDOS           # 19845 (cada pedido guarda su lista en ID_GVA10)
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
            r = self._crear_renglon(lista, art, nuevo_precio, quien, id_cliente, codigo_cliente)
            self._invalidar()
            return r

    def _crear_renglon(self, lista: dict, art, precio: float, quien: str,
                       id_cliente: int | None = None, codigo_cliente: str = "", anotar: bool = True) -> dict:
        """Crea el renglon en Tango (sin controles; los hace quien llama, con el lock tomado)."""
        id_lista = lista["ID_GVA10"]
        registro = {
            "ID_STA11": art.id, "DECIMALES_RESTO": None, "DECIMALES_GVA17": lista.get("DECIMALES") or 2,
            "NRO_DE_LIS": lista.get("NRO_DE_LIS"), "COD_ARTICU": art.codigo, "ID_GVA10": id_lista,
            "PRECIO": 0 if id_cliente is not None else precio, "BASE": False, "FILLER": "", "GVA13": [],
        }
        nuevo_id = self._c.crear(PROCESO_RENGLONES, registro)
        if not nuevo_id:
            raise TangoError("Tango no devolvió el número del renglón nuevo.")
        if id_cliente is not None:
            creado = self._leer_renglon(nuevo_id)
            creado["GVA13"] = [{
                "ACTUALIZAR_CONTROL_PRECIOS": False, "ID_GVA10": id_lista, "ID_STA11": art.id, "ID_GVA14": id_cliente,
                "FILLER": "", "COD_ARTICU": art.codigo, "COD_CLIENT": codigo_cliente,
                "NRO_LISTA": lista.get("NRO_DE_LIS"), "PRECIO": precio, "ID_GVA17": nuevo_id,
            }]
            self._c.actualizar(PROCESO_RENGLONES, creado)
        despues_crudo = self._leer_renglon(nuevo_id)
        despues = _resumen(despues_crudo)
        if anotar:
            self.registro.anotar(quien, "agregar artículo", lista=lista.get("NOMBRE_LIS"), articulo=art.codigo,
                                 cliente=codigo_cliente or None, despues=despues)
        guardado = (despues_crudo.get("PRECIO") if id_cliente is None else
                    next((c.get("PRECIO") for c in despues_crudo.get("GVA13") or [] if c.get("ID_GVA14") == id_cliente), None))
        if guardado != precio:
            raise TangoError(f"Se creó el renglón de {art.codigo} pero el precio guardado no coincide. Revisalo en Tango.")
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

    def crear_lista(self, nombre: str, moneda: str, quien: str, numero: int | None = None,
                    id_cliente: int | None = None) -> dict:
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
        salida = {"id": nuevo_id, "numero": int(numero), "nombre": nombre}
        if id_cliente:
            # La lista ya quedo creada; si falla la asignacion se avisa, pero no se deshace
            try:
                salida["asignada"] = self.asignar_lista(nuevo_id, id_cliente, quien)
            except (PedidoInvalido, TangoError) as e:
                salida["error_asignacion"] = str(e)
        return salida

    def eliminar_lista(self, id_lista: int, confirmar_nombre: str, quien: str,
                       reasignar_a: int | None = None) -> dict:
        """Borra la lista. Si hay clientes que la usan, con reasignar_a primero se les
        asigna esa otra lista (si no, se niega: quedarian apuntando a una lista inexistente)."""
        self._sin_pedidos(id_lista)
        reasignados = []
        if reasignar_a:
            if reasignar_a == id_lista:
                raise PedidoInvalido("Elegí otra lista para los clientes.")
            with self._lock:
                lista = self._lista(id_lista)
                self._lista(reasignar_a)                     # que exista
                nombre = (lista.get("NOMBRE_LIS") or "").strip()
                if " ".join((confirmar_nombre or "").split()).upper() != nombre.upper():
                    raise PedidoInvalido("Para eliminar la lista escribí su nombre exacto.")
                clientes, _ = self._servicio.clientes(forzar=True)
                usan = [c for c in clientes if c.lista_precios.strip().upper() == nombre.upper()]
            for c in usan:
                try:
                    self.asignar_lista(reasignar_a, c.id, quien)
                except (PedidoInvalido, TangoError) as e:
                    hechos = f" Ya se cambió en: {', '.join(reasignados)}." if reasignados else ""
                    raise TangoError(f"No se pudo cambiar la lista de {c.razon_social}: {e}.{hechos} La lista no se eliminó.") from None
                reasignados.append(c.razon_social)
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
            # 1) Copia de todo lo que tiene, al registro, ANTES de tocar nada: si algo
            #    falla a mitad de camino, lo que se quito se puede volver a cargar.
            completos = [x for x in (self._c.obtener(PROCESO_RENGLONES, r["ID_GVA17"]) for r in filas) if x]
            copia = [{"articulo": x.get("COD_ARTICU"), **_resumen(x)} for x in completos]
            self.registro.anotar(quien, "eliminar lista", lista=nombre, numero=lista.get("NRO_DE_LIS"),
                                 articulos=len(copia), contenido=copia)
            # 2) Primero se intenta borrar la lista tal como esta. Si Tango la rechaza por
            #    pedidos (aunque esten anulados) no se toco nada; si la borra, se limpian los
            #    renglones que hayan quedado. Solo si la rechaza por otro motivo (por ejemplo,
            #    porque todavia tiene articulos) se quitan los articulos y se reintenta.
            try:
                self._c.borrar(PROCESO_LISTAS, id_lista)
                borrada = not self._c.obtener(PROCESO_LISTAS, id_lista)
            except TangoError as e:
                if re.search(r"\bpedidos\b", str(e).lower()):     # "...datos relacionados en Pedidos"
                    self.registro.anotar(quien, "error al eliminar lista", lista=nombre, articulos_quitados=0, error=str(e))
                    self._invalidar()
                    raise TangoError(f"Tango no dejó eliminar la lista {nombre}: {e}. Aunque estén anulados, los pedidos "
                                     "siguen apuntando a la lista. No se tocó nada.") from None
                borrada = False
            if borrada:
                sueltos = 0
                for actual in completos:
                    try:
                        if self._c.obtener(PROCESO_RENGLONES, actual["ID_GVA17"]):
                            self._borrar_renglon(actual)
                            sueltos += 1
                    except TangoError:
                        pass
                self._invalidar()
                return {"articulos_quitados": len(completos), "clientes_reasignados": reasignados}
            # 3) Quitar los articulos y borrar la lista
            quitados = 0
            try:
                for actual in completos:
                    self._borrar_renglon(actual)
                    quitados += 1
                self._c.borrar(PROCESO_LISTAS, id_lista)
                if self._c.obtener(PROCESO_LISTAS, id_lista):
                    raise TangoError("Tango respondió bien pero la lista sigue existiendo.")
            except TangoError as e:
                self.registro.anotar(quien, "error al eliminar lista", lista=nombre, articulos_quitados=quitados,
                                     error=str(e))
                quitado = (f" Ya se habían quitado {quitados} de sus {len(copia)} artículos; están copiados en "
                           "«Ver cambios» para volver a cargarlos." if quitados else "")
                if "renglón" in str(e) or (completos and quitados < len(completos)):
                    raise TangoError(f"Tango no dejó quitar los artículos de la lista {nombre}: {e}.{quitado}") from None
                # Paso con LABORATORIO (19/11/2026): la API respondio "Registro inexistente" y la
                # pantalla de Listas de precios de Tango la borro sin problema.
                raise TangoError(f"Tango no dejó eliminar la lista {nombre} desde la Herramienta ({e}).{quitado} "
                                 "La lista quedó vacía: eliminala desde Tango, en Ventas > Listas de precios "
                                 "(Tango web, proceso 984), con el botón Eliminar.") from None
            finally:
                self._invalidar()
            return {"articulos_quitados": quitados, "clientes_reasignados": reasignados}

    def _sin_pedidos(self, id_lista: int) -> None:
        """Tango no deja borrar una lista que usa algun pedido ("existen datos relacionados
        en Pedidos"), y lo dice recien al final, con los articulos ya quitados
        (REPOSICION, 19/11/2026). Se revisa antes de tocar nada."""
        pedidos = self._c.listar(PROCESO_PEDIDOS)
        usan = [p for p in pedidos if p.get("ID_GVA10") == id_lista]
        if pedidos and "ID_GVA10" not in pedidos[0]:
            completos = self._detalles_proceso(PROCESO_PEDIDOS, [p["ID_GVA21"] for p in pedidos if p.get("ID_GVA21")])
            usan = [p for p in completos.values() if p.get("ID_GVA10") == id_lista]
        # Si todos los que la usan estan anulados, se deja que Tango decida (se intenta borrar
        # la lista primero, sin tocar articulos)
        usan = [p for p in usan if p.get("ESTADO") != 5]
        if usan:
            nros = ", ".join(sorted({str(p.get("NRO_PEDIDO") or "").strip()[-8:].lstrip("0") or "?" for p in usan})[:5])
            mensaje = (f"No se puede eliminar: la usan {len(usan)} pedido{'s' if len(usan) > 1 else ''} en Tango "
                       f"(número {nros}) y Tango no deja borrar una lista con pedidos. No se tocó nada.")
            mensaje += (" Anulá esos pedidos en Tango (Ventas > Pedidos > Anular) y volvé a intentar.")
            raise PedidoInvalido(mensaje)

    def _detalles_proceso(self, proceso: int, ids: list[int]) -> dict[int, dict]:
        with ThreadPoolExecutor(max_workers=8) as ex:
            return {i: d for i, d in zip(ids, ex.map(lambda i: self._c.obtener(proceso, i), ids)) if d}

    # ---------------------------------------------------------------- restaurar
    def copia_de(self, fecha: str, lista: str) -> dict:
        for c in self.registro.ultimos(5000):
            if c.get("accion") == "eliminar lista" and c.get("fecha") == fecha and c.get("lista") == lista:
                return c
        raise PedidoInvalido("No encontré esa copia en el registro de cambios.")

    def estado_restauracion(self) -> dict:
        return dict(getattr(self, "_restauracion", None) or {"corriendo": False})

    def restaurar_lista(self, fecha: str, nombre_lista: str, quien: str) -> dict:
        """Vuelve a cargar en la lista lo que tenia al eliminarla (copia del registro).
        Corre en un hilo aparte; los articulos que ya estan en la lista se saltean."""
        if getattr(self, "_restauracion", None) and self._restauracion.get("corriendo"):
            raise PedidoInvalido("Ya hay una restauración en curso.")
        copia = self.copia_de(fecha, nombre_lista)
        lista = next((x for x in self._listas_crudas()
                      if (x.get("NOMBRE_LIS") or "").strip().upper() == nombre_lista.strip().upper()), None)
        if not lista:
            raise PedidoInvalido(f"La lista {nombre_lista} ya no existe en Tango: creala de nuevo con el mismo nombre "
                                 f"(número {copia.get('numero')}) y volvé a tocar Restaurar.")
        ya = {(r.get("COD_STA11") or r.get("COD_ARTICU") or "").strip()
              for r in self._todos_los_renglones(forzar=True) if r.get("ID_GVA10") == lista["ID_GVA10"]}
        pendientes = [x for x in copia.get("contenido") or [] if x.get("articulo") not in ya]
        self._restauracion = {"corriendo": True, "lista": nombre_lista, "total": len(pendientes), "hechos": 0,
                              "ya_estaban": len(copia.get("contenido") or []) - len(pendientes), "errores": []}
        threading.Thread(target=self._restaurar, args=(lista, pendientes, quien), daemon=True).start()
        return self.estado_restauracion()

    def _restaurar(self, lista: dict, pendientes: list[dict], quien: str) -> None:
        estado = self._restauracion
        try:
            articulos = {a.codigo: a for a in self._servicio.articulos()[0]}
            clientes = self._clientes_por_codigo()
        except TangoError as e:
            estado.update(corriendo=False, errores=[{"articulo": "", "error": str(e)}])
            return
        for x in pendientes:
            try:
                art = articulos.get(x.get("articulo"))
                if not art:
                    raise PedidoInvalido("ese artículo ya no existe en Tango")
                with self._lock:
                    r = self._crear_renglon(lista, art, x.get("precio") or 0, quien, anotar=False)
                    especiales = []
                    for e in x.get("especiales") or []:
                        cli = clientes.get(e.get("cliente"))
                        if not cli:
                            raise PedidoInvalido(f"el cliente {e.get('cliente')} del precio especial ya no existe")
                        especiales.append({
                            "ACTUALIZAR_CONTROL_PRECIOS": False, "ID_GVA10": lista["ID_GVA10"], "ID_STA11": art.id,
                            "ID_GVA14": cli.id, "FILLER": "", "COD_ARTICU": art.codigo, "COD_CLIENT": cli.codigo,
                            "NRO_LISTA": lista.get("NRO_DE_LIS"), "PRECIO": e.get("precio"), "ID_GVA17": r["id"]})
                    if especiales:
                        actual = self._leer_renglon(r["id"])
                        self._c.actualizar(PROCESO_RENGLONES, {**actual, "GVA13": especiales})
            except (PedidoInvalido, TangoError) as e:
                estado["errores"].append({"articulo": x.get("articulo"), "error": str(e)})
            estado["hechos"] += 1
        self._invalidar()
        estado["corriendo"] = False
        self.registro.anotar(quien, "restaurar lista", lista=lista.get("NOMBRE_LIS"), articulos=estado["hechos"] - len(estado["errores"]),
                             errores=estado["errores"][:50])

    def asignar_lista(self, id_lista: int, id_cliente: int, quien: str) -> dict:
        """Cambia la lista de precios en la ficha del cliente (proceso 2117).

        La ficha guarda la lista en dos campos: ID_GVA10 (id interno) y NRO_LISTA
        (numero). Se lee la ficha completa, se cambian solo esos dos y se manda
        entera; probado el 19/11/2026 con AERARG: no cambia nada mas que FECHA_MODI.
        """
        if not id_lista or not id_cliente:
            raise PedidoInvalido("Elegí la lista y el cliente.")
        with self._lock:
            lista = self._lista(id_lista)
            ficha = self._c.obtener(PROCESO_CLIENTES, id_cliente)
            if not ficha:
                raise PedidoInvalido("Ese cliente ya no existe en Tango.")
            nro = lista.get("NRO_DE_LIS")
            antes = {"id": ficha.get("ID_GVA10"), "numero": ficha.get("NRO_LISTA")}
            cliente = {"id": id_cliente, "codigo": (ficha.get("COD_GVA14") or "").strip(),
                       "razon_social": (ficha.get("RAZON_SOCI") or "").strip()}
            if antes["id"] == id_lista:
                return {"cliente": cliente, "lista": lista.get("NOMBRE_LIS"), "sin_cambios": True}
            nombres = {x.get("ID_GVA10"): (x.get("NOMBRE_LIS") or "").strip() for x in self._listas_crudas()}
            self._c.actualizar(PROCESO_CLIENTES, {**ficha, "ID_GVA10": id_lista, "NRO_LISTA": nro})
            despues = self._c.obtener(PROCESO_CLIENTES, id_cliente) or {}
            self._servicio.olvidar("clientes")
            if despues.get("ID_GVA10") != id_lista:
                raise TangoError("Tango no guardó la lista en la ficha del cliente.")
            self.registro.anotar(quien, "asignar lista", cliente=cliente["codigo"], razon_social=cliente["razon_social"],
                                 lista=(lista.get("NOMBRE_LIS") or "").strip(), numero=nro,
                                 lista_anterior=nombres.get(antes["id"]) or antes["numero"],
                                 numero_anterior=antes["numero"])
            return {"cliente": cliente, "lista": (lista.get("NOMBRE_LIS") or "").strip(),
                    "anterior": nombres.get(antes["id"]) or f"Lista {antes['numero']}"}
