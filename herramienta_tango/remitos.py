"""
Pantalla de Remitos: los remitos del ultimo año, con el pedido (o los pedidos) de cada uno.

La lista sale de la consulta Live de comprobantes de venta (API). El vinculo con el pedido
se lee de la base (que renglones de stock apuntan a que pedido), porque el pedido de Tango
guarda solo su ultimo remito: con entregas parciales, los remitos anteriores quedarian como
"sin pedido". Si la base no esta disponible, se usa ese ultimo remito y se avisa.
Solo lectura.
"""

from __future__ import annotations

from . import base_tango
from .tango.modelos import Remito, solo_digitos


def _corto(numero: str) -> str:
    """'R0000800000110' -> 'R 00008-00000110', como lo muestra la lista de Tango."""
    d = solo_digitos(numero)
    letra = numero[:1] if numero[:1].isalpha() else ""
    return f"{letra} {d[:-8]}-{d[-8:]}".strip() if len(d) > 8 else numero


def _clave(numero: str) -> str:
    return solo_digitos(numero).lstrip("0")


def vista(servicio, forzar: bool = False) -> dict:
    remitos, momento = servicio.remitos(forzar)
    try:
        pedidos, _ = servicio.pedidos(forzar)
    except Exception:
        pedidos = []
    por_id = {p.id: p for p in pedidos if p.id is not None}
    por_numero = {_clave(p.numero): p for p in pedidos}

    def pedido_dict(id_pedido, numero):
        p = por_id.get(id_pedido) or por_numero.get(_clave(numero or ""))
        return {"id": p.id if p else id_pedido, "numero": (p.numero if p else numero) or "",
                "orden_compra": p.orden_compra_cliente if p else "", "estado": p.estado if p else None}

    origen, aviso, mapa, facturas, estado_f, posibles, anulados = "base", "", {}, {}, set(), {}, {}
    try:
        datos = base_tango.remitos_con_pedido()
        if not datos.get("relacion"):
            raise base_tango.BaseNoDisponible("No se encontró en la base la columna que une remitos y pedidos.")
        mapa = {_clave(k): v for k, v in (datos.get("remitos") or {}).items()}
        facturas = {_clave(k): v for k, v in (datos.get("facturas") or {}).items()}
        if not datos.get("facturas_leidas", True):
            facturas = None
        estado_f = {_clave(k) for k in datos.get("estado_f") or []}
        posibles = {_clave(k): v for k, v in (datos.get("posibles") or {}).items()}
        anulados = {_clave(a["numero"]): a for a in datos.get("anulados") or []}
    except base_tango.BaseNoDisponible as e:
        origen = "ultimo_remito"
        aviso = (f"{e} Se muestra el pedido solo para el último remito de cada pedido: con entregas parciales, "
                 "los remitos anteriores pueden figurar como sin pedido.")

    # Los anulados no vienen en la consulta de Tango: se suman desde la base
    en_lista = {_clave(r.numero) for r in remitos}
    remitos = list(remitos) + [Remito(id=a["id"], numero=a["numero"], numero_corto=_corto(a["numero"]), fecha=a["fecha"],
                                      id_cliente=a["id_cliente"], codigo_cliente=a["codigo_cliente"], cliente=a["cliente"],
                                      estado="anulado")
                               for k, a in anulados.items() if k not in en_lista]
    remitos.sort(key=lambda r: (r.fecha or "", r.numero), reverse=True)
    salida = []
    for r in remitos:
        anulado = anulados.get(_clave(r.numero))
        if origen == "base":
            peds = [pedido_dict(x.get("id"), x.get("numero")) for x in mapa.get(_clave(r.numero), [])]
        else:
            peds = [pedido_dict(None, r.pedido)] if r.pedido else []
        facs = facturas.get(_clave(r.numero), []) if origen == "base" and facturas is not None and not anulado else None
        # "Sin facturar" solo si no hay factura vinculada y Tango tampoco lo marca como facturado (estado F)
        segun_tango = facs is not None and not facs and _clave(r.numero) in estado_f
        sin_facturar = facs is not None and not facs and not segun_tango
        salida.append({"id": r.id, "numero": r.numero, "numero_corto": r.numero_corto, "fecha": r.fecha,
                       "id_cliente": r.id_cliente, "codigo_cliente": r.codigo_cliente, "cliente": r.cliente,
                       "estado": r.estado, "pedidos": peds,
                       "facturas": facs, "facturado_segun_tango": segun_tango, "sin_facturar": sin_facturar,
                       "posibles_facturas": posibles.get(_clave(r.numero), []) if sin_facturar else [],
                       "anulado": bool(anulado),
                       "fecha_anulacion": anulado.get("fecha_anulacion") if anulado else None,
                       "usuario_anulacion": anulado.get("usuario_anulacion") if anulado else ""})
    return {"remitos": salida, "origen": origen, "aviso": aviso}, momento


def renglones(id_remito: int) -> dict:
    return base_tango.renglones_remito(id_remito)


def diagnostico(servicio) -> dict:
    """Busca en la base que une remitos y pedidos, partiendo del remito mas reciente que un
    pedido tiene como ultimo remito (un par seguro)."""
    remitos, _ = servicio.remitos(False)
    pedidos, _ = servicio.pedidos(False)
    por_numero = {_clave(p.numero): p for p in pedidos}
    for r in remitos:
        p = por_numero.get(_clave(r.pedido)) if r.pedido else None
        if p and r.id:
            return {"par": {"remito": r.numero, "id_remito": r.id, "pedido": p.numero, "id_pedido": p.id},
                    **base_tango.diag_pedido_remito(p.id, r.id)}
    return {"error": "No encontré ningún remito que un pedido tenga como último remito."}
