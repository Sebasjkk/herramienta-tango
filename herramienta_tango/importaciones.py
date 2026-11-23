"""
Importaciones: lo que esta en camino y el precio de compra de cada articulo.

Se lee de la base de Tango (solo lectura, con base_tango):
  CPA65  carpetas de importacion (cabecera: fecha, estado, proveedor, moneda...)
  CPA66  renglones de cada carpeta: CANT_PEDID (pedido), CANT_NACIO (ya nacionalizado,
         o sea llego por despacho), CANT_FACTU, PREC_ORIG (precio del proveedor) y
         CAN_EQUIVA (equivalencia entre la unidad de compra y la de stock)
  STA08  partidas: las que creo cada despacho de la carpeta (N_DESPACHO, FECHA)
  CPA01  proveedores

"En camino" = pedido - nacionalizado, en carpetas que no estan cerradas.
De la cabecera (CPA65) los nombres de algunas columnas varian: se buscan por nombre
parecido y la respuesta dice cuales encontro, para poder ajustarlo si hace falta.
"""

from __future__ import annotations

import re
from collections import defaultdict

EPS = 0.0001


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _txt(v) -> str:
    return "" if v is None else str(v).strip()


def numero_carpeta(id_carpeta: str) -> str:
    """'0000100000979' -> '00001-00000979' (como la muestra Tango)."""
    d = re.sub(r"\D", "", id_carpeta or "")
    return f"{d[:-8].zfill(5)}-{d[-8:]}" if len(d) > 8 else (id_carpeta or "").strip()


def numero_corto(id_carpeta: str) -> str:
    d = re.sub(r"\D", "", id_carpeta or "")
    if not d:
        return (id_carpeta or "").strip()
    return d[-8:].lstrip("0") or "0"


def _campo(fila: dict, *patrones: str):
    """El valor de la primera columna cuyo nombre coincide (exacto o que empiece) con alguno de los patrones."""
    claves = {k.upper(): k for k in fila}
    for p in patrones:
        if p in claves and fila[claves[p]] not in (None, ""):
            return fila[claves[p]]
    for p in patrones:
        for k in claves:
            if k.startswith(p) and fila[claves[k]] not in (None, ""):
                return fila[claves[k]]
    return None


def _cerrada(estado) -> bool:
    t = _txt(estado).upper()
    return t in ("C", "CE", "CERRADA", "CERRADO", "F", "FINALIZADA") or t.startswith("CERR")


def _moneda(cab: dict) -> str:
    if "MON_CTE" in {k.upper() for k in cab}:
        v = _campo(cab, "MON_CTE")
        if isinstance(v, bool):
            return "$" if v else "US$"
        if _txt(v).upper() in ("S", "1", "TRUE"):
            return "$"
        if _txt(v).upper() in ("N", "0", "FALSE"):
            return "US$"
    m = _txt(_campo(cab, "MONEDA", "COD_MONEDA", "DESC_MONED"))
    return {"D.M.": "US$", "DM": "US$", "U$S": "US$", "USD": "US$", "DOLAR": "US$"}.get(m.upper(), m)


def armar(datos: dict) -> dict:
    """De las filas leidas de la base a carpetas y a un resumen por articulo."""
    filas = lambda k: [] if datos.get(k) is None else (datos[k] if isinstance(datos[k], list) else [datos[k]])
    cabeceras = {}
    for c in filas("carpetas"):
        idc = _txt(_campo(c, "ID_CARPETA", "N_CARPETA", "NRO_CARPETA"))
        if not idc:
            continue
        estado = _campo(c, "ESTADO", "EST_CARPET", "CERRADA")
        cabeceras[idc] = {
            "id": idc, "numero": numero_carpeta(idc), "corto": numero_corto(idc),
            "fecha": _txt(_campo(c, "FECHA_APER", "FECHA_ALTA", "FECHA_EMIS", "FECHA"))[:10] or None,
            "estado": _txt(estado), "cerrada": _cerrada(estado),
            "proveedor": _txt(_campo(c, "NOMBRE_PROVEEDOR")) or _txt(_campo(c, "COD_PROVEE")),
            "moneda": _moneda(c), "cotizacion": _num(_campo(c, "COTIZACION", "COTIZ")) or None,
            "referencia": _txt(_campo(c, "LEYENDA", "OBSERVACIO", "REFERENCIA", "DESCRIPCIO")),
            "renglones": [], "despachos": [],
        }
    for d in filas("despachos"):
        idc = _txt(d.get("ID_CARPETA"))
        if idc in cabeceras:
            x = {"despacho": _txt(d.get("N_DESPACHO")), "partida": _txt(d.get("N_PARTIDA")), "fecha": _txt(d.get("FECHA"))[:10] or None}
            if x not in cabeceras[idc]["despachos"]:
                cabeceras[idc]["despachos"].append(x)

    por_articulo: dict[str, dict] = defaultdict(lambda: {"en_camino": 0.0, "carpetas_en_camino": [], "compras": []})
    for r in filas("renglones"):
        idc = _txt(r.get("ID_CARPETA"))
        cab = cabeceras.get(idc)
        if cab is None:
            cab = cabeceras[idc] = {"id": idc, "numero": numero_carpeta(idc), "corto": numero_corto(idc), "fecha": None, "estado": "",
                                    "cerrada": False, "proveedor": "", "moneda": "", "cotizacion": None, "referencia": "",
                                    "renglones": [], "despachos": []}
        cod = _txt(r.get("COD_ARTICU"))
        eq = _num(r.get("CAN_EQUIVA")) or 1.0
        pedido, llego = _num(r.get("CANT_PEDID")), _num(r.get("CANT_NACIO"))
        falta = max(0.0, pedido - llego)
        precio = _num(r.get("PREC_ORIG"))
        renglon = {"codigo": cod, "pedido": round(pedido, 4), "nacionalizado": round(llego, 4), "facturado": round(_num(r.get("CANT_FACTU")), 4),
                   "falta": round(falta, 4), "equivalencia": eq, "precio": round(precio, 4),
                   # en unidad de stock: la cantidad de compra por la equivalencia; el precio, dividido
                   "falta_stock": round(falta * eq, 4), "precio_stock": round(precio / eq, 4) if eq else None}
        cab["renglones"].append(renglon)
        a = por_articulo[cod]
        if falta > EPS and not cab["cerrada"]:
            a["en_camino"] += falta * eq
            a["carpetas_en_camino"].append({"carpeta": cab["numero"], "corto": cab["corto"], "fecha": cab["fecha"], "proveedor": cab["proveedor"],
                                            "falta": renglon["falta_stock"], "pedido": round(pedido * eq, 4), "llego": round(llego * eq, 4),
                                            "estado": cab["estado"]})
        if precio > 0:
            a["compras"].append({"carpeta": cab["numero"], "corto": cab["corto"], "fecha": cab["fecha"], "proveedor": cab["proveedor"],
                                 "moneda": cab["moneda"], "precio": renglon["precio_stock"], "precio_compra": precio, "equivalencia": eq,
                                 "cantidad": round(pedido * eq, 4)})
    for a in por_articulo.values():
        a["en_camino"] = round(a["en_camino"], 4)
        a["compras"].sort(key=lambda x: (x["fecha"] or "", x["carpeta"]), reverse=True)
        a["ultima_compra"] = a["compras"][0] if a["compras"] else None
        a["compras"] = a["compras"][:10]
    carpetas = sorted(cabeceras.values(), key=lambda c: (c["fecha"] or "", c["id"]), reverse=True)
    columnas = filas("columnas")
    return {"carpetas": carpetas, "articulos": {k: v for k, v in por_articulo.items() if k},
            "columnas_carpeta": [_txt(x) for x in columnas]}
