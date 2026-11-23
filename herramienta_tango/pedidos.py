"""
Pedidos de venta (proceso 19845): detalle y baja.

Crear y borrar pedidos por la API no se puede con la licencia de Sianco ("Su
licencia no incluye el uso del API de Transacciones Tango Ventas", probado el
19/11/2026 con el alta y con la baja del pedido 12). La pantalla ya no ofrece
eliminar; eliminar() queda por si se compra el modulo.

Antes de borrar, la copia completa del pedido (con renglones y notas) queda en
cambios_pedidos.jsonl de la carpeta del programa.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from . import config
from .precios import PedidoInvalido, RegistroCambios
from .tango import TangoError, procesos

# Estados de GVA21 en Tango
ESTADOS = {1: "Ingresado", 2: "Aprobado", 3: "Cumplido", 4: "Cerrado", 5: "Anulado", 6: "Desaprobado"}


def _txt(v) -> str:
    return " ".join(str(v).split()) if v is not None else ""


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


EPS = 0.0001
CONSULTAS_EN_PARALELO = 6


def renglon_con_entrega(r: dict) -> dict:
    """Un renglon de RENGLON_DTO con lo pedido, lo entregado y lo que falta.
    "Cantidad a descargar" es lo que todavia no se remitio de ese renglon."""
    pedido = _num(r.get("CANTIDAD_PEDIDA"))
    falta = max(0.0, _num(r.get("CANTIDAD_A_DESCARGAR")))
    return {
        "codigo": _txt(next((r[k] for k in ("COD_ARTICULO", "CODIGO_ARTICULO", "COD_STA11", "COD_ARTICU") if r.get(k)), "")),
        "descripcion": _txt(r.get("DESCRIPCION_ARTICULO")),
        "adicional": _txt(r.get("DESCRIPCION_ADICIONAL_ARTICULO")),
        "cantidad": r.get("CANTIDAD_PEDIDA"),
        "entregado": round(max(0.0, pedido - falta), 4),
        "falta": round(min(falta, pedido) if pedido > 0 else falta, 4),
        "pendiente_facturar": r.get("CANTIDAD_PENDIENTE_A_FACTURAR"),
        "a_descargar": r.get("CANTIDAD_A_DESCARGAR"),
        "precio": r.get("PRECIO"),
        "bonificacion": r.get("PORCENTAJE_BONIFICACION"),
        "importe": r.get("IMPORTE"),
    }


def resumen_entrega(renglones: list[dict]) -> dict:
    """sin entregar / parcial / entregado, con el porcentaje (por cantidad: los renglones son del mismo tipo de unidad casi siempre)."""
    pedido = sum(_num(r["cantidad"]) for r in renglones)
    entregado = sum(r["entregado"] for r in renglones)
    falta = sum(r["falta"] for r in renglones)
    if falta <= EPS:
        estado = "entregado"
    elif entregado <= EPS:
        estado = "sin_entregar"
    else:
        estado = "parcial"
    return {"estado_entrega": estado, "pedido": round(pedido, 4), "entregado": round(entregado, 4), "falta": round(falta, 4),
            "porcentaje": round(100 * entregado / pedido) if pedido > EPS else 0,
            "renglones_con_falta": sum(1 for r in renglones if r["falta"] > EPS)}


class EditorPedidos:
    def __init__(self, cliente, servicio, registro: RegistroCambios | None = None):
        self._c = cliente
        self._servicio = servicio
        self.registro = registro or RegistroCambios(config.CARPETA / "cambios_pedidos.jsonl")
        self._lock = threading.Lock()

    def detalle(self, id_pedido: int) -> dict:
        v = self._c.obtener(procesos.PEDIDOS, id_pedido)
        if not v:
            raise PedidoInvalido("Ese pedido ya no existe en Tango.")
        lista = ""
        if v.get("ID_GVA10"):
            try:
                l = self._c.obtener(procesos.LISTAS_PRECIOS, v["ID_GVA10"])
                lista = _txt((l or {}).get("NOMBRE_LIS")) or f"Lista {(l or {}).get('NRO_DE_LIS', '')}"
            except TangoError:
                pass
        cliente = {}
        try:
            c = self._c.obtener(procesos.CLIENTES, v.get("ID_GVA14")) if v.get("ID_GVA14") else None
            if c:
                cliente = {"codigo": _txt(c.get("COD_GVA14")), "razon_social": _txt(c.get("RAZON_SOCI"))}
        except TangoError:
            pass
        renglones = [renglon_con_entrega(r) for r in v.get("RENGLON_DTO") or []]
        return {
            "id": v.get("ID_GVA21"), "numero": _txt(v.get("NRO_PEDIDO")),
            "fecha": (v.get("FECHA_PEDIDO") or "")[:10] or None,
            "fecha_entrega": (v.get("FECHA_ENTREGA") or "")[:10] or None,
            "estado": v.get("ESTADO"), "estado_texto": ESTADOS.get(v.get("ESTADO"), str(v.get("ESTADO"))),
            "cliente": cliente, "lista_precios": lista, "moneda_extranjera": v.get("ID_MONEDA") == 2,
            "cotizacion": v.get("COTIZACION"),
            "orden_compra": _txt(v.get("NRO_ORDEN_COMPRA")),
            "leyendas": [_txt(v.get(f"LEYENDA_{i}")) for i in range(1, 6) if _txt(v.get(f"LEYENDA_{i}"))],
            "observaciones": _txt(v.get("OBSERVACIONES")),
            "comprometido": bool(v.get("COMPROMETE_STOCK")),
            "renglones": renglones,
            "entrega": resumen_entrega(renglones),
            "ultimo_remito": _txt(v.get("N_REMITO")),
            "notas": [_txt(n.get("MENSAJE")) for n in v.get("NOTA_PEDIDO_DTO") or []],
        }

    def avance(self, ids: list[int]) -> dict[int, dict]:
        """Cuanto se entrego de cada pedido. Tango lo informa por renglon en el detalle del pedido,
        asi que se pide el detalle de cada uno (de a varios a la vez). Un pedido que falla queda afuera."""
        def uno(id_pedido):
            try:
                v = self._c.obtener(procesos.PEDIDOS, id_pedido)
            except TangoError:
                return id_pedido, None
            if not v:
                return id_pedido, None
            renglones = [renglon_con_entrega(r) for r in v.get("RENGLON_DTO") or []]
            return id_pedido, {**resumen_entrega(renglones),
                               "renglones": [{k: r[k] for k in ("codigo", "descripcion", "cantidad", "entregado", "falta")} for r in renglones]}
        with ThreadPoolExecutor(max_workers=CONSULTAS_EN_PARALELO) as ex:
            return {i: d for i, d in ex.map(uno, ids) if d is not None}

    def eliminar(self, id_pedido: int, confirmar_numero: str, quien: str) -> dict:
        with self._lock:
            v = self._c.obtener(procesos.PEDIDOS, id_pedido)
            if not v:
                raise PedidoInvalido("Ese pedido ya no existe en Tango.")
            numero = _txt(v.get("NRO_PEDIDO"))
            corto = numero[-8:].lstrip("0") or "0"        # sin el prefijo de la sucursal, como en pantalla
            pedido = "".join((confirmar_numero or "").split()).lstrip("0") or ""
            if pedido != corto:
                raise PedidoInvalido(f"Para eliminar el pedido escribí su número: {corto}.")
            # Copia completa antes de tocar nada
            self.registro.anotar(quien, "eliminar pedido", pedido=numero, copia=v)
            try:
                self._c.borrar(procesos.PEDIDOS, id_pedido)
                if self._c.obtener(procesos.PEDIDOS, id_pedido):
                    raise TangoError("Tango respondió bien pero el pedido sigue existiendo.")
            except TangoError as e:
                self.registro.anotar(quien, "error al eliminar pedido", pedido=numero, error=str(e))
                raise TangoError(f"Tango no dejó eliminar el pedido {corto}: {e}") from None
            finally:
                self._servicio.olvidar("pedidos")
            return {"eliminado": numero}
