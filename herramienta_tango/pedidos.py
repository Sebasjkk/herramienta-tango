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

from . import config
from .precios import PedidoInvalido, RegistroCambios
from .tango import TangoError, procesos

# Estados de GVA21 en Tango
ESTADOS = {1: "Ingresado", 2: "Aprobado", 3: "Cumplido", 4: "Cerrado", 5: "Anulado", 6: "Desaprobado"}


def _txt(v) -> str:
    return " ".join(str(v).split()) if v is not None else ""


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
        renglones = [{
            "descripcion": _txt(r.get("DESCRIPCION_ARTICULO")),
            "adicional": _txt(r.get("DESCRIPCION_ADICIONAL_ARTICULO")),
            "cantidad": r.get("CANTIDAD_PEDIDA"),
            "pendiente_facturar": r.get("CANTIDAD_PENDIENTE_A_FACTURAR"),
            "a_descargar": r.get("CANTIDAD_A_DESCARGAR"),
            "precio": r.get("PRECIO"),
            "bonificacion": r.get("PORCENTAJE_BONIFICACION"),
            "importe": r.get("IMPORTE"),
        } for r in v.get("RENGLON_DTO") or []]
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
            "notas": [_txt(n.get("MENSAJE")) for n in v.get("NOTA_PEDIDO_DTO") or []],
        }

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
