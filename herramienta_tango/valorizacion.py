"""
Valorizacion del stock: cuanta plata hay en el deposito 1 (CENTRAL), en dolares, al costo.

No escribe nada en Tango. Lee la base (solo lectura, con base_tango) y calcula igual que la
Simulacion de Generacion de costos de importacion (verificado el 11/11/2026 contra las
carpetas 862 y 979):

  Costo de una partida que vino por despacho =
      precio de la factura de importacion (gasto PRE de la carpeta, CPA71) / cantidad facturada (CPA66,
      pasada a unidad de stock con CAN_EQUIVA)
    + gastos de despacho cargados en Tango (los demas gastos de CPA71, ya repartidos por Tango
      a cada partida-articulo en CPA74) / cantidad que entro por ese despacho (STA10.CANT_DESPA)
  Todo en dolares: un gasto en pesos (MON_CTE verdadero) se divide por su cotizacion.

Para cada renglon (articulo + partida) con saldo en Central se usa, en este orden:
  1. "carpeta":  el costo de la carpeta de su despacho (lo de arriba).
  2. "tango":    el costo que ya tiene grabado la partida en Tango (COSTO_EX), si es mayor a cero
                 (por ejemplo, un ajuste valorizado AJV).
  3. "ultima":   el precio de la ultima importacion del mismo articulo (sin gastos).
  4. "sin":      sin costo. Se muestra aparte; no suma.

Fuera del total: saldos negativos, el articulo INSUMOS y los articulos que no llevan partidas
(se listan con un valor estimado, aparte).
"""

from __future__ import annotations

from collections import defaultdict

from .importaciones import _campo, _num, _txt, numero_corto

DEPOSITO = "1"
EXCLUIDOS = {"INSUMOS"}
VERIFICAR_COSTO = 2000.0      # costo unitario en USD desde el que conviene ver que exista
VERIFICAR_VALOR = 10000.0     # valor del renglon en USD desde el que conviene ver que exista
EPS = 0.000001

ORIGENES = {
    "carpeta": "Carpeta de importación de la partida",
    "tango": "Costo grabado en Tango",
    "ultima": "Última importación del artículo",
    "sin": "Sin costo",
}


def _lista(datos: dict, k: str) -> list:
    v = datos.get(k)
    return [] if v is None else (v if isinstance(v, list) else [v])


def _en_pesos(v) -> bool:
    """MON_CTE: verdadero = moneda corriente (pesos); falso = moneda extranjera."""
    if isinstance(v, bool):
        return v
    return _txt(v).upper() in ("TRUE", "S", "SI", "1", "T")


def _usd(importe: float, mon_cte, cotizacion: float) -> float | None:
    if _en_pesos(mon_cte):
        return importe / cotizacion if cotizacion > EPS else None
    return importe


def _dep(v) -> str:
    return _txt(v).lstrip("0") or _txt(v)


def calcular(datos: dict) -> dict:
    """De las filas leidas de la base al detalle valorizado y los resumenes."""
    descripciones = {_txt(a.get("COD_ARTICU")): _txt(a.get("DESCRIPCIO")) for a in _lista(datos, "articulos")}
    partidas = {}
    for p in _lista(datos, "partidas"):
        partidas[_txt(p.get("ID_STA08"))] = {
            "partida": _txt(p.get("N_PARTIDA")), "despacho": _txt(p.get("N_DESPACHO")),
            "carpeta": _txt(p.get("ID_CARPETA")), "fecha": _txt(p.get("FECHA"))[:10] or None,
        }

    # --- precio de factura (PRE) por carpeta y articulo, en USD por unidad de stock
    #     (la cantidad facturada esta en la unidad de compra: por la equivalencia pasa a la de stock,
    #     igual que en Importaciones; ej. comprado en libras y stock en kilos)
    facturado: dict[tuple, float] = defaultdict(float)
    for r in _lista(datos, "renglones"):
        facturado[(_txt(r.get("ID_CARPETA")), _txt(r.get("COD_ARTICU")))] += _num(r.get("CANT_FACTU")) * (_num(r.get("CAN_EQUIVA")) or 1.0)
    pre: dict[tuple, float] = defaultdict(float)
    gastos_usd: dict[str, tuple[float, float]] = {}       # ID_DISTRIB -> (importe original, importe USD)
    for g in _lista(datos, "gastos"):
        importe = _num(_campo(g, "IMPORTE"))
        usd = _usd(importe, _campo(g, "MON_CTE"), _num(_campo(g, "COTIZACION")))
        if usd is None:
            continue
        if _txt(_campo(g, "COD_GASTO")).upper() == "PRE":
            pre[(_txt(g.get("ID_CARPETA")), _txt(g.get("COD_ARTICU")))] += usd
        else:
            idd = _txt(_campo(g, "ID_DISTRIB"))
            if idd:
                o, u = gastos_usd.get(idd, (0.0, 0.0))
                gastos_usd[idd] = (o + importe, u + usd)
    costo_pre = {k: v / facturado[k] for k, v in pre.items() if facturado.get(k, 0) > EPS}

    # --- gastos de despacho repartidos por Tango a cada partida-articulo (CPA74), en USD
    des: dict[tuple, float] = defaultdict(float)
    for d in _lista(datos, "distribucion"):
        o_u = gastos_usd.get(_txt(_campo(d, "ID_DISTRIB")))
        if not o_u or abs(o_u[0]) < EPS:
            continue
        des[(_txt(d.get("N_PARTIDA")), _txt(d.get("COD_ARTICU")))] += _num(_campo(d, "IMPORTE")) * o_u[1] / o_u[0]
    despachado: dict[tuple, float] = defaultdict(float)
    saldos = _lista(datos, "saldos")
    for s in saldos:
        despachado[(_txt(s.get("N_PARTIDA")), _txt(s.get("COD_ARTICU")))] += _num(s.get("CANT_DESPA"))

    # --- referencia: la ultima importacion (por fecha de la partida) de cada articulo con precio
    ultima: dict[str, dict] = {}
    for s in saldos:
        cod = _txt(s.get("COD_ARTICU"))
        p = partidas.get(_txt(s.get("ID_STA08"))) or {}
        k = (p.get("carpeta") or "", cod)
        if k[0] and k in costo_pre:
            f = p.get("fecha") or ""
            if cod not in ultima or f > ultima[cod]["fecha"]:
                ultima[cod] = {"fecha": f, "costo": costo_pre[k], "carpeta": numero_corto(k[0])}

    filas, negativos, con_partidas = [], [], set()
    for s in saldos:
        cod = _txt(s.get("COD_ARTICU"))
        con_partidas.add(cod)
        if _dep(s.get("COD_DEPOSI")) != DEPOSITO or cod.upper() in EXCLUIDOS:
            continue
        cant = _num(s.get("CANTIDAD"))
        if abs(cant) < EPS:
            continue
        p = partidas.get(_txt(s.get("ID_STA08"))) or {}
        npart = _txt(s.get("N_PARTIDA")) or p.get("partida", "")
        idc = p.get("carpeta") or ""
        costo_tango = _num(s.get("COSTO_EX"))
        referencia = ""
        if idc and (idc, cod) in costo_pre:
            unidades = despachado.get((npart, cod), 0)
            gasto = des.get((npart, cod), 0) / unidades if unidades > EPS else 0.0
            costo, origen, referencia = costo_pre[(idc, cod)] + gasto, "carpeta", numero_corto(idc)
        elif costo_tango > EPS:
            costo, origen = costo_tango, "tango"
        elif cod in ultima:
            costo, origen, referencia = ultima[cod]["costo"], "ultima", ultima[cod]["carpeta"]
        else:
            costo, origen = None, "sin"
        fecha = p.get("fecha")
        fila = {
            "codigo": cod, "descripcion": descripciones.get(cod, ""), "partida": npart,
            "despacho": p.get("despacho", ""), "carpeta": numero_corto(idc) if idc else "",
            "fecha": fecha, "anio": fecha[:4] if fecha else "",
            "cantidad": round(cant, 4), "costo": round(costo, 4) if costo is not None else None,
            "valor": round(cant * costo, 2) if costo is not None else None,
            "origen": origen, "referencia": referencia,
            "costo_tango": round(costo_tango, 4) if costo_tango > EPS else None,
        }
        if cant < 0:
            negativos.append(fila)
            continue
        fila["verificar"] = costo is not None and (costo >= VERIFICAR_COSTO or cant * costo >= VERIFICAR_VALOR)
        filas.append(fila)
    filas.sort(key=lambda f: -(f["valor"] or 0))
    negativos.sort(key=lambda f: f["cantidad"])

    # --- articulos sin partidas con saldo en Central (catalogo viejo): aparte, valor estimado
    sin_partidas = []
    for a in _lista(datos, "sin_partidas"):
        cod = _txt(a.get("COD_ARTICU"))
        if not cod or cod in con_partidas or cod.upper() in EXCLUIDOS or _dep(_campo(a, "COD_DEPOSI")) != DEPOSITO:
            continue
        cant = _num(_campo(a, "CANT_STOCK", "CANTIDAD", "SALDO"))
        if abs(cant) < EPS:
            continue
        ref = ultima.get(cod)
        sin_partidas.append({"codigo": cod, "descripcion": descripciones.get(cod, ""), "cantidad": round(cant, 4),
                             "costo": round(ref["costo"], 4) if ref else None,
                             "valor": round(cant * ref["costo"], 2) if ref and cant > 0 else None})
    sin_partidas.sort(key=lambda f: (f["cantidad"] < 0, -(f["valor"] or 0), f["codigo"]))

    return {"filas": filas, "negativos": negativos, "sin_partidas": sin_partidas,
            "resumen": resumir(filas, negativos, sin_partidas),
            "criterio": {"deposito": DEPOSITO, "excluidos": sorted(EXCLUIDOS), "verificar_costo": VERIFICAR_COSTO,
                         "verificar_valor": VERIFICAR_VALOR, "origenes": ORIGENES}}


def resumir(filas: list, negativos: list, sin_partidas: list) -> dict:
    por_origen = {k: {"renglones": 0, "valor": 0.0} for k in ORIGENES}
    por_anio: dict[str, dict] = defaultdict(lambda: {"renglones": 0, "valor": 0.0})
    for f in filas:
        o = por_origen[f["origen"]]
        o["renglones"] += 1
        o["valor"] += f["valor"] or 0
        a = por_anio[f["anio"] or "Sin fecha"]
        a["renglones"] += 1
        a["valor"] += f["valor"] or 0
    for o in por_origen.values():
        o["valor"] = round(o["valor"], 2)
    verificar = [f for f in filas if f.get("verificar")]
    return {
        "total": round(sum(f["valor"] or 0 for f in filas), 2),
        "renglones": len(filas),
        "articulos": len({f["codigo"] for f in filas}),
        "por_origen": por_origen,
        "por_anio": [{"anio": k, "renglones": v["renglones"], "valor": round(v["valor"], 2)} for k, v in sorted(por_anio.items())],
        "verificar": {"renglones": len(verificar), "valor": round(sum(f["valor"] for f in verificar), 2)},
        "negativos": {"renglones": len(negativos)},
        "sin_partidas": {"articulos": len(sin_partidas),
                         "valor_estimado": round(sum(f["valor"] or 0 for f in sin_partidas), 2)},
    }


def excel(r: dict, fecha: str) -> bytes:
    """Libro con el resumen y el detalle (lo mismo que la pantalla)."""
    from . import xlsx
    res = r["resumen"]
    n, t = "numero", "texto"
    resumen = [["Total valorizado (USD)", res["total"]],
               ["Renglones con saldo", res["renglones"]],
               ["Artículos", res["articulos"]],
               ["Fecha del cálculo", fecha], ["", None], ["Por origen del costo", None]]
    for k, o in res["por_origen"].items():
        resumen.append([ORIGENES[k] + f" ({o['renglones']} renglones)", o["valor"]])
    resumen += [["", None], ["Por año de la partida", None]]
    resumen += [[a["anio"] + f" ({a['renglones']} renglones)", a["valor"]] for a in res["por_anio"]]
    resumen += [["", None],
                [f"Para verificar ({res['verificar']['renglones']} renglones)", res["verificar"]["valor"]],
                [f"Saldos negativos, fuera del total ({res['negativos']['renglones']} renglones)", None],
                [f"Artículos sin partidas, fuera del total ({res['sin_partidas']['articulos']}), valor estimado",
                 res["sin_partidas"]["valor_estimado"]],
                ["", None],
                ["Criterio", None],
                ["Depósito 1 (CENTRAL), sin INSUMOS, en dólares. Costo = factura de importación + gastos de despacho cargados en Tango.", None],
                ["No incluye derechos ni gastos que no estén cargados en Tango.", None]]
    cols = [("Código", t), ("Descripción", t), ("Partida", t), ("Despacho", t), ("Carpeta", t), ("Fecha partida", t),
            ("Cantidad", n), ("Costo unitario USD", n), ("Valor USD", n), ("Origen del costo", t), ("Carpeta de referencia", t)]

    def det(fs):
        return [[f["codigo"], f["descripcion"], f["partida"], f["despacho"], f["carpeta"], f["fecha"] or "",
                 f["cantidad"], f["costo"], f["valor"], ORIGENES[f["origen"]], f["referencia"]] for f in fs]

    hojas = [("Resumen", [("Concepto", t), ("USD", n)], resumen),
             ("Detalle", cols, det(r["filas"])),
             ("Para verificar", cols, det([f for f in r["filas"] if f.get("verificar")])),
             ("Sin costo", cols, det([f for f in r["filas"] if f["origen"] == "sin"])),
             ("Saldos negativos", cols, det(r["negativos"])),
             ("Sin partidas", [("Código", t), ("Descripción", t), ("Cantidad", n), ("Costo estimado USD", n), ("Valor estimado USD", n)],
              [[f["codigo"], f["descripcion"], f["cantidad"], f["costo"], f["valor"]] for f in r["sin_partidas"]])]
    return xlsx.escribir_libro(hojas)
