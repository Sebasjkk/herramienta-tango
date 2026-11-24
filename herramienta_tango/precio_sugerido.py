"""
Precio sugerido: lo que hace falta tener a mano para ponerle precio a un articulo
para un cliente.

- Ultimas ventas del articulo a ese cliente y a otros (facturas de la base, solo lectura).
- Precio en la lista de precios del cliente (precio especial del cliente si lo tiene).
- Costo en dolares: el de la Valorizacion (carpeta de importacion + gastos cargados en
  Tango, promedio del stock de Central), o si no hay stock, la ultima importacion.
- Margen de cada precio sobre ese costo.

No graba nada. El costo va en un pedido aparte porque la Valorizacion tarda la primera vez.
"""

from __future__ import annotations

from . import base_tango

MAX_VENTAS = 12


def _margen(precio, costo):
    if not precio or not costo or precio <= 0:
        return None
    return round((precio - costo) / precio * 100, 1)


def _cliente(servicio, codigo: str):
    codigo = (codigo or "").strip().upper()
    if not codigo:
        return None
    for c in servicio.clientes()[0]:
        if c.codigo.strip().upper() == codigo:
            return c
    return None


def precio_en_lista(precios: list[dict], cliente) -> dict | None:
    """El precio del articulo en la lista del cliente: el especial del cliente o el de lista."""
    if not cliente or not cliente.lista_precios:
        return None
    nombre = cliente.lista_precios.strip().upper()
    for p in precios:
        if (p.get("lista") or "").strip().upper() != nombre:
            continue
        esp = next((e for e in p.get("especiales") or [] if (e.get("codigo_cliente") or "").strip().upper()
                    == cliente.codigo.strip().upper()), None)
        precio = esp["precio"] if esp and esp.get("precio") else p.get("precio")
        return {"lista": p.get("lista"), "moneda": p.get("moneda"), "precio": precio or None,
                "especial": bool(esp and esp.get("precio")), "id_renglon": p.get("id")}
    return {"lista": cliente.lista_precios, "moneda": None, "precio": None, "especial": False, "id_renglon": None,
            "no_esta": True}


def armar(servicio, codigo: str, codigo_cliente: str) -> dict:
    codigo = (codigo or "").strip()
    cliente = _cliente(servicio, codigo_cliente)
    art = next((a for a in servicio.articulos()[0] if a.codigo.strip() == codigo), None)
    precios = servicio.editor.precios_de_articulo(codigo)
    res = {
        "articulo": {"codigo": codigo, "descripcion": art.descripcion if art else "", "unidad": art.unidad if art else ""},
        "cliente": {"codigo": cliente.codigo, "razon_social": cliente.razon_social, "lista": cliente.lista_precios} if cliente else None,
        "en_lista": precio_en_lista(precios, cliente),
        "otras_listas": [{"lista": p.get("lista"), "moneda": p.get("moneda"), "precio": p.get("precio")}
                         for p in precios if p.get("precio")],
    }
    try:
        ventas = base_tango.ventas_articulo(codigo)
        filas = ventas["filas"]
        cod = cliente.codigo.strip().upper() if cliente else None
        res["ventas_cliente"] = [f for f in filas if cod and f["codigo_cliente"].upper() == cod][:MAX_VENTAS]
        res["ventas_otros"] = [f for f in filas if not cod or f["codigo_cliente"].upper() != cod][:MAX_VENTAS]
        res["ventas_aviso"] = ventas.get("aviso")
    except base_tango.BaseNoDisponible as e:
        res["ventas_cliente"], res["ventas_otros"], res["ventas_error"] = [], [], str(e)
    return res


def costo(servicio, codigo: str) -> dict:
    """Costo unitario en USD del articulo: stock de Central valorizado, o ultima importacion."""
    codigo = (codigo or "").strip()
    res = {"codigo": codigo, "costo": None, "origen": None, "detalle": []}
    try:
        val = base_tango.valorizacion_datos(False)
    except base_tango.BaseNoDisponible as e:
        res["error"] = str(e)
        return res
    filas = [f for f in val.get("filas", []) if f.get("codigo") == codigo and f.get("costo")]
    cant = sum(f["cantidad"] for f in filas)
    if filas and cant > 0:
        res["costo"] = round(sum(f["cantidad"] * f["costo"] for f in filas) / cant, 4)
        res["origen"] = "stock"
        res["detalle"] = [{"partida": f["partida"], "carpeta": f.get("carpeta"), "fecha": f.get("fecha"),
                           "cantidad": f["cantidad"], "costo": f["costo"], "origen": f.get("origen")} for f in filas]
        return res
    try:
        imp = base_tango.importaciones_datos(False)
        ultima = ((imp.get("articulos") or {}).get(codigo) or {}).get("ultima_compra")
    except base_tango.BaseNoDisponible:
        ultima = None
    if ultima and ultima.get("precio"):
        res["costo"] = round(ultima["precio"], 4)
        res["origen"] = "ultima_importacion"
        res["detalle"] = [{"carpeta": ultima.get("corto") or ultima.get("carpeta"), "fecha": ultima.get("fecha"),
                           "proveedor": ultima.get("proveedor"), "moneda": ultima.get("moneda")}]
    return res


def margen(precio, costo_usd):
    return _margen(precio, costo_usd)
