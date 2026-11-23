"""
Comparar el inventario del Excel (Inventario_Metco_*.xls) con el stock de Tango.

Del Excel se leen las hojas de inventario ("Inv. Alambre", "Inv. Polvo",
"Inv. Repuesto", "Inv. Soldadura"): codigo SAP, cantidad y unidad. El codigo
SAP es el codigo de articulo de Tango; se compara sin los ceros de adelante
(en el Excel a veces es un numero, 1000125, y en Tango un texto, 01000125).

Polvos y alambres estan en libras en el Excel y en kilos en Tango: se pasan a
kilos. La comparacion principal es contra el deposito Central (el que importa
para el inventario); los otros depositos se muestran aparte para que no se
mezclen, que fue lo que confundio una comparacion anterior.

Solo lee: no toca Tango. Devuelve el resumen y un Excel con el detalle.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

from . import xls, xlsx

LIBRA_KG = 0.45359237
DEPOSITO_PRINCIPAL = "CENTRAL"
TOLERANCIA = 0.01            # unidades
TOLERANCIA_KG = 0.05         # kilos (el Excel pasa de libras con decimales largos)
TOLERANCIA_RELATIVA = 0.005  # 0,5 %
EPS = 0.0001

UNIDADES_KG = {"KG", "KGR", "KGS", "KILO", "KILOS", "KILOGRAMO", "KILOGRAMOS"}
UNIDADES_LB = {"LB", "LBS", "LIBRA", "LIBRAS"}


class InventarioInvalido(ValueError):
    pass


def _norm_codigo(c: str) -> str:
    return re.sub(r"\s+", "", str(c or "")).upper().lstrip("0")


def _codigo_excel(v) -> str:
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else repr(v)
    return str(v or "").strip()


def _numero(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace(" ", "")
    if not t:
        return None
    t = t.replace(".", "").replace(",", ".") if "," in t else t
    try:
        return float(t)
    except ValueError:
        return None


def _columna(encabezado: list, *nombres) -> int | None:
    norm = [re.sub(r"[^a-z]", "", str(h or "").lower().replace("ó", "o").replace("í", "i")) for h in encabezado]
    for n in nombres:
        if n in norm:
            return norm.index(n)
    return None


# ------------------------------------------------------------------ Excel
def leer_excel(contenido: bytes) -> tuple[list[dict], dict[str, list[str]]]:
    """Renglones de las hojas de inventario, y en que otras hojas (Obsoletos, Usados) aparece cada codigo."""
    try:
        hojas = xls.leer(contenido) if xls.es_xls(contenido) else xlsx.leer(contenido)
    except (xls.XlsInvalido, xlsx.ExcelInvalido) as e:
        raise InventarioInvalido(str(e)) from None
    inventario = [n for n in hojas if n.strip().lower().startswith("inv")]
    if not inventario:
        raise InventarioInvalido("El Excel no tiene hojas de inventario (las que empiezan con «Inv.», como «Inv. Polvo»).")
    renglones = []
    for hoja in inventario:
        filas = hojas[hoja]
        if not filas:
            continue
        enc = filas[0]
        c_cant = _columna(enc, "cantidad")
        c_sap = _columna(enc, "sap", "codigo")
        c_desc = _columna(enc, "descripcion")
        c_uni = _columna(enc, "unidad")
        c_kg = _columna(enc, "kg")
        c_ubi = _columna(enc, "ubicacion")
        if c_cant is None or (c_sap is None and c_desc is None):
            continue
        tipo = re.sub(r"(?i)^inv\.?\s*", "", hoja).strip() or hoja
        for i, f in enumerate(filas[1:], start=2):
            val = lambda c: f[c] if c is not None and c < len(f) else None
            codigo = _codigo_excel(val(c_sap))
            desc = str(val(c_desc) or "").strip()
            if not codigo and not desc:
                continue
            cant = _numero(val(c_cant))
            renglones.append({
                "hoja": hoja, "fila": i, "tipo": tipo, "codigo": codigo, "descripcion": desc,
                "cantidad": cant if cant is not None else 0.0, "cantidad_vacia": cant is None,
                "unidad": str(val(c_uni) or "").strip().lower() if c_uni is not None else "",
                "kg": _numero(val(c_kg)), "ubicacion": str(val(c_ubi) or "").strip(),
            })
    otras: dict[str, list[str]] = defaultdict(list)
    for hoja in hojas:
        if hoja in inventario or not re.search(r"(?i)obsolet|usad", hoja):
            continue
        for f in hojas[hoja][1:]:
            for v in f:
                if isinstance(v, float) and v == int(v) and v > 999:
                    n = _norm_codigo(str(int(v)))
                    if hoja not in otras[n]:
                        otras[n].append(hoja)
    return renglones, otras


def _en_unidad_tango(r: dict, unidad_tango: str) -> tuple[float | None, str]:
    """La cantidad del Excel en la unidad de stock de Tango. None si no se puede convertir."""
    u_exc, u_tan = r["unidad"], (unidad_tango or "").strip().upper()
    q = r["cantidad"]
    if u_tan in UNIDADES_KG:
        if u_exc in ("lbs", "lb", "libras"):
            return (r["kg"] if r["kg"] is not None and abs(r["kg"] - q * LIBRA_KG) < 0.01 else q * LIBRA_KG), "lbs → kg"
        if u_exc in ("kg", "kgs", "kilos", ""):
            return q, ""
        return None, f"El Excel dice «{u_exc}» y Tango lleva el stock en kg"
    if u_tan in UNIDADES_LB:
        if u_exc in ("kg", "kgs"):
            return q / LIBRA_KG, "kg → lbs"
        return q, ""
    if u_exc in ("lbs", "lb", "kg") and u_tan:
        return None, f"El Excel dice «{u_exc}» y Tango lleva el stock en «{u_tan.lower()}»"
    return q, ""


# ------------------------------------------------------------------ comparar
def comparar(contenido: bytes, servicio, nombre_archivo: str = "") -> dict:
    renglones, otras_hojas = leer_excel(contenido)
    articulos, _ = servicio.articulos()
    partidas, momento = servicio.saldos_por_partida()
    por_articulo, _ = servicio.saldos_por_articulo()

    arts = {a.codigo: a for a in articulos}
    por_norm: dict[str, list[str]] = defaultdict(list)
    for a in articulos:
        por_norm[_norm_codigo(a.codigo)].append(a.codigo)
    # Saldo por articulo y deposito: por partida para los que llevan partidas, por articulo para el resto
    saldo: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for p in partidas:
        saldo[p.codigo_articulo][p.deposito.strip().upper() or "?"] += p.saldo
        if p.codigo_articulo not in arts:
            por_norm[_norm_codigo(p.codigo_articulo)].append(p.codigo_articulo)
    for s in por_articulo:
        a = arts.get(s.codigo_articulo)
        if a is not None and not a.usa_partidas:
            saldo[s.codigo_articulo][s.deposito.strip().upper() or "?"] += s.saldo

    def descripcion_tango(cod):
        a = arts.get(cod)
        if a:
            return a.descripcion
        return next((p.descripcion for p in partidas if p.codigo_articulo == cod), "")

    # El mismo codigo puede aparecer mas de una vez en el Excel: se suma y se avisa
    grupos: dict[str, list[dict]] = defaultdict(list)
    for r in renglones:
        grupos[_norm_codigo(r["codigo"] or r["descripcion"])].append(r)

    vistos_tango: set[str] = set()
    filas = []
    for clave, rs in grupos.items():
        r0 = rs[0]
        candidatos = por_norm.get(clave, []) if clave else []
        if r0["codigo"] and r0["codigo"] in arts:
            candidatos = sorted(set(candidatos) | {r0["codigo"]})
        codigos = sorted(set(candidatos), key=lambda c: (c != r0["codigo"], -abs(sum(saldo[c].values())), c))
        vistos_tango.update(codigos)
        principal = codigos[0] if codigos else ""
        a = arts.get(principal)
        unidad_tango = a.unidad if a else ""
        central = sum(saldo[c].get(DEPOSITO_PRINCIPAL, 0.0) for c in codigos)
        otros: dict[str, float] = defaultdict(float)
        for c in codigos:
            for dep, v in saldo[c].items():
                if dep != DEPOSITO_PRINCIPAL:
                    otros[dep] += v
        convertidos = [_en_unidad_tango(r, unidad_tango) for r in rs]
        notas = []
        if any(q is None for q, _ in convertidos):
            excel_t = None
            notas.append(next(n for q, n in convertidos if q is None))
        else:
            excel_t = sum(q for q, _ in convertidos)
        if len(rs) > 1:
            notas.append(f"Aparece {len(rs)} veces en el Excel ({', '.join(sorted({r['hoja'] for r in rs}))}): se sumaron")
        if len(codigos) > 1:
            notas.append("En Tango hay más de un código para este artículo: " + ", ".join(codigos))
        if any(r["cantidad_vacia"] for r in rs):
            notas.append("Cantidad vacía en el Excel (se tomó 0)")
        otros_txt = ", ".join(f"{d.title()} {v:g}" for d, v in sorted(otros.items()) if abs(v) > EPS)
        if otros_txt:
            notas.append("Además hay stock en otros depósitos")
        if not r0["codigo"]:
            notas.append("Sin código SAP en el Excel: se buscó por la descripción")

        if not codigos:
            estado = "No está en Tango"
            dif = None
        elif excel_t is None:
            estado = "Revisar unidad"
            dif = None
        else:
            dif = central - excel_t
            tol = max(TOLERANCIA_KG if (unidad_tango or "").upper() in UNIDADES_KG else TOLERANCIA,
                      TOLERANCIA_RELATIVA * max(abs(central), abs(excel_t)))
            estado = "Coincide" if abs(dif) <= tol else ("Tango tiene más" if dif > 0 else "Tango tiene menos")
        filas.append({
            "estado": estado, "tipo": r0["tipo"], "codigo_excel": r0["codigo"], "descripcion_excel": r0["descripcion"],
            "cantidad_excel": round(sum(r["cantidad"] for r in rs), 4), "unidad_excel": r0["unidad"] or ("un" if r0["tipo"].lower().startswith("rep") else ""),
            "excel_en_unidad_tango": None if excel_t is None else round(excel_t, 4),
            "codigo_tango": principal, "descripcion_tango": descripcion_tango(principal) if principal else "",
            "unidad_tango": unidad_tango, "tango_central": round(central, 4), "tango_otros_depositos": otros_txt,
            "tango_total": round(central + sum(otros.values()), 4),
            "diferencia": None if dif is None else round(dif, 4),
            "ubicacion": ", ".join(sorted({r["ubicacion"] for r in rs if r["ubicacion"]})),
            "filas_excel": ", ".join(f"{r['hoja']} fila {r['fila']}" for r in rs),
            "notas": "; ".join(notas),
        })

    # Lo que Tango tiene con saldo y el Excel no menciona
    for cod, deps in saldo.items():
        if cod in vistos_tango:
            continue
        central = deps.get(DEPOSITO_PRINCIPAL, 0.0)
        otros = {d: v for d, v in deps.items() if d != DEPOSITO_PRINCIPAL and abs(v) > EPS}
        if abs(central) <= EPS and not otros:
            continue
        en_otras = otras_hojas.get(_norm_codigo(cod), [])
        a = arts.get(cod)
        filas.append({
            "estado": "Solo en Tango", "tipo": "", "codigo_excel": "", "descripcion_excel": "",
            "cantidad_excel": None, "unidad_excel": "", "excel_en_unidad_tango": None,
            "codigo_tango": cod, "descripcion_tango": descripcion_tango(cod), "unidad_tango": a.unidad if a else "",
            "tango_central": round(central, 4),
            "tango_otros_depositos": ", ".join(f"{d.title()} {v:g}" for d, v in sorted(otros.items())),
            "tango_total": round(sum(deps.values()), 4), "diferencia": round(central, 4), "ubicacion": "", "filas_excel": "",
            "notas": ("En el Excel figura en " + ", ".join(en_otras)) if en_otras else "",
        })

    orden = {"Tango tiene menos": 0, "Tango tiene más": 1, "Revisar unidad": 2, "No está en Tango": 3, "Solo en Tango": 4, "Coincide": 5}
    filas.sort(key=lambda f: (orden.get(f["estado"], 9), -abs(f["diferencia"] or 0), f["codigo_tango"] or f["codigo_excel"]))
    cuenta = defaultdict(int)
    for f in filas:
        cuenta[f["estado"]] += 1
    con_stock_excel = sum(1 for f in filas if (f["cantidad_excel"] or 0) > EPS)
    resumen = {
        "archivo": nombre_archivo, "saldos_tango": datetime.fromtimestamp(momento).isoformat(timespec="minutes"),
        "renglones_excel": len(renglones), "articulos_comparados": len(grupos), "con_stock_en_excel": con_stock_excel,
        "estados": dict(cuenta), "hojas": sorted({r["hoja"] for r in renglones}),
    }
    return {"resumen": resumen, "filas": filas, "archivo": excel_resultados(resumen, filas)}


# ------------------------------------------------------------------ Excel de resultados
COLUMNAS = [
    ("Estado", "texto", "estado"), ("Tipo", "texto", "tipo"), ("Código Excel", "texto", "codigo_excel"),
    ("Descripción Excel", "texto", "descripcion_excel"), ("Cantidad Excel", "numero", "cantidad_excel"),
    ("Unidad Excel", "texto", "unidad_excel"), ("Excel en unidad de Tango", "numero", "excel_en_unidad_tango"),
    ("Código Tango", "texto", "codigo_tango"), ("Descripción Tango", "texto", "descripcion_tango"),
    ("Unidad Tango", "texto", "unidad_tango"), ("Tango Central", "numero", "tango_central"),
    ("Diferencia (Tango − Excel)", "numero", "diferencia"), ("Otros depósitos", "texto", "tango_otros_depositos"),
    ("Tango total", "numero", "tango_total"), ("Ubicación", "texto", "ubicacion"), ("Filas del Excel", "texto", "filas_excel"),
    ("Notas", "texto", "notas"),
]


def excel_resultados(resumen: dict, filas: list[dict]) -> bytes:
    cols = [(t, tipo) for t, tipo, _ in COLUMNAS]
    a_fila = lambda f: [f[k] for _, _, k in COLUMNAS]
    est = resumen["estados"]
    texto = [
        ["Comparación del inventario del Excel con el stock de Tango"],
        ["Archivo", resumen["archivo"]],
        ["Saldos de Tango al", resumen["saldos_tango"].replace("T", " ")],
        ["Hojas leídas", ", ".join(resumen["hojas"])],
        ["Artículos del Excel comparados", resumen["articulos_comparados"]],
        [],
        ["Coinciden", est.get("Coincide", 0)],
        ["Tango tiene menos que el Excel", est.get("Tango tiene menos", 0)],
        ["Tango tiene más que el Excel", est.get("Tango tiene más", 0)],
        ["Unidad para revisar", est.get("Revisar unidad", 0)],
        ["Están en el Excel y no en Tango", est.get("No está en Tango", 0)],
        ["Tienen stock en Tango y no están en el Excel", est.get("Solo en Tango", 0)],
        [],
        ["Cómo leerlo"],
        ["La comparación es contra el depósito Central. Lo que hay en otros depósitos se muestra aparte y no entra en la diferencia."],
        ["Polvos y alambres: el Excel está en libras y Tango en kilos; se pasaron a kilos (1 lb = 0,45359237 kg)."],
        ["Los códigos se comparan sin los ceros de adelante. Diferencia = Tango Central − Excel."],
        ["Si el Excel es de hace unos días, los remitos y ajustes posteriores también aparecen como diferencia."],
        ["Esta comparación no modifica nada en Tango."],
    ]
    hojas = [("Resumen", [("Dato", "texto"), ("Valor", "texto")], texto)]
    grupos = [("Diferencias", ("Tango tiene menos", "Tango tiene más")), ("Revisar unidad", ("Revisar unidad",)),
              ("No están en Tango", ("No está en Tango",)), ("Solo en Tango", ("Solo en Tango",)), ("Coinciden", ("Coincide",))]
    for nombre, estados in grupos:
        hojas.append((nombre, cols, [a_fila(f) for f in filas if f["estado"] in estados]))
    hojas.append(("Todo", cols, [a_fila(f) for f in filas]))
    return xlsx.escribir_libro(hojas)
