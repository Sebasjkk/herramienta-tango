"""
Recuentos de stock: contar todo el deposito Central (no solo lo que tiene diferencias con el
Excel) y dejarlo guardado en la Herramienta para volver a usarlo.

Un recuento tiene nombre y fecha; cada conteo guarda la cantidad contada, cuanto decia Tango
EN ESE MOMENTO (para que el ajuste no cambie si despues sale un remito), quien y cuando. La
clave de cada conteo es articulo + partida ("" para los articulos sin partidas).

Ajustar Tango: la API no deja grabar ajustes (401), asi que se arma la planilla de "Ajustes de
stock" para importar, escribiendo sobre la plantilla original que baja Tango (tiene una hoja
oculta _metadata que la valida). Esa plantilla se carga una vez desde la pantalla y queda en la
carpeta del programa. La planilla lleva solo los renglones con diferencia: contado - Tango, con
signo (positivo entra, negativo sale).

Guardado en recuentos.json (carpeta del programa). Solo la Herramienta escribe ahi; Tango no se toca.
"""

from __future__ import annotations

import io
import json
import re
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from . import config, xlsx
from .precios import PedidoInvalido

MAX_NOMBRE = 60
MAX_NOTA = 200
EPS = 0.0001
# Estados de la comparacion con el inventario Excel que cuentan como diferencia (inventario.py)
ESTADOS_DIFERENCIA = ("Tango tiene más", "Tango tiene menos", "Revisar unidad")


def ruta_registro() -> Path:
    return config.CARPETA / "recuentos.json"


def ruta_plantilla() -> Path:
    return config.CARPETA / "plantilla_ajuste_stock.xlsx"


def clave(codigo: str, partida: str) -> str:
    return f"{(codigo or '').strip()}|{(partida or '').strip()}"


def _numero(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        n = float(str(v).replace(",", ".")) if not isinstance(v, (int, float)) else float(v)
    except ValueError:
        raise PedidoInvalido("La cantidad tiene que ser un número.") from None
    if n < 0:
        raise PedidoInvalido("La cantidad contada no puede ser negativa.")
    return round(n, 4)


class Recuentos:
    def __init__(self, ruta: Path | None = None):
        self.ruta = ruta or ruta_registro()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ archivo
    def _leer(self) -> list[dict]:
        try:
            return json.loads(self.ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []

    def _guardar(self, datos: list[dict]) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.ruta)

    def _buscar(self, datos: list[dict], id_recuento: int) -> dict:
        r = next((x for x in datos if x["id"] == id_recuento), None)
        if not r:
            raise PedidoInvalido("Ese recuento no existe.")
        return r

    # ------------------------------------------------------------ consultas
    def todos(self) -> list[dict]:
        with self._lock:
            salida = []
            for r in sorted(self._leer(), key=lambda x: x["id"], reverse=True):
                conteos = r.get("conteos", {}).values()
                salida.append({k: v for k, v in r.items() if k not in ("conteos", "referencia")} | {
                    "contados": len(conteos),
                    "con_diferencia": sum(1 for c in conteos if abs(c["cantidad"] - c["tango"]) > EPS)})
            return salida

    def uno(self, id_recuento: int) -> dict:
        with self._lock:
            return self._buscar(self._leer(), id_recuento)

    # ------------------------------------------------------------ cambios
    def crear(self, nombre: str, quien: str) -> dict:
        nombre = (nombre or "").strip()[:MAX_NOMBRE]
        if not nombre:
            raise PedidoInvalido("Poné un nombre para el recuento (por ejemplo: Recuento diciembre).")
        with self._lock:
            datos = self._leer()
            r = {"id": max([x["id"] for x in datos] + [0]) + 1, "nombre": nombre, "deposito": "CENTRAL",
                 "creado": datetime.now().isoformat(timespec="seconds"), "creado_por": quien,
                 "estado": "abierto", "conteos": {}}
            datos.append(r)
            self._guardar(datos)
            return {k: v for k, v in r.items() if k != "conteos"}

    def contar(self, id_recuento: int, codigo: str, partida: str, cantidad, tango, quien: str,
               nota: str = "", unidad: str = "", descripcion: str = "", nueva: bool = False) -> dict:
        """Guarda (o borra, si cantidad viene vacia) el conteo de un articulo + partida.
        tango: el saldo que mostraba la pantalla al contar; la diferencia es contado - tango."""
        codigo = (codigo or "").strip()
        if not codigo:
            raise PedidoInvalido("Falta el artículo.")
        cant = _numero(cantidad)
        with self._lock:
            datos = self._leer()
            r = self._buscar(datos, id_recuento)
            if r.get("estado") != "abierto":
                raise PedidoInvalido("Ese recuento está cerrado: reabrilo para seguir contando.")
            k = clave(codigo, partida)
            if cant is None:
                r["conteos"].pop(k, None)
                self._guardar(datos)
                return {"clave": k, "borrado": True}
            previo = r["conteos"].get(k) or {}
            c = {"codigo": codigo, "partida": (partida or "").strip(), "cantidad": cant,
                 # cuanto decia Tango en el momento de contar (si se recuenta, la foto se renueva)
                 "tango": round(float(tango or 0), 4),
                 "unidad": (unidad or previo.get("unidad") or "").strip(),
                 "descripcion": (descripcion or previo.get("descripcion") or "").strip()[:120],
                 "nueva": bool(nueva or previo.get("nueva")), "nota": (nota or "").strip()[:MAX_NOTA],
                 "quien": quien, "cuando": datetime.now().isoformat(timespec="seconds")}
            r["conteos"][k] = c
            self._guardar(datos)
            return {"clave": k, **c}

    def cambiar_estado(self, id_recuento: int, estado: str, quien: str) -> dict:
        if estado not in ("abierto", "cerrado"):
            raise PedidoInvalido("Estado inválido.")
        with self._lock:
            datos = self._leer()
            r = self._buscar(datos, id_recuento)
            r["estado"] = estado
            r[f"{estado}_por"] = quien
            r[f"{estado}_el"] = datetime.now().isoformat(timespec="seconds")
            self._guardar(datos)
            return {k: v for k, v in r.items() if k not in ("conteos", "referencia")}

    def borrar(self, id_recuento: int, confirmar: str) -> dict:
        with self._lock:
            datos = self._leer()
            r = self._buscar(datos, id_recuento)
            if (confirmar or "").strip().lower() != r["nombre"].strip().lower():
                raise PedidoInvalido("Para borrarlo, escribí el nombre del recuento tal cual.")
            self._guardar([x for x in datos if x["id"] != id_recuento])
            return {"borrado": r["nombre"]}

    def cargar_referencia(self, id_recuento: int, contenido: bytes, servicio=None, nombre_archivo: str = "") -> dict:
        """Guarda, por artículo, qué dice el inventario Excel frente a Tango: sirve para contar solo lo
        que difiere. Acepta el Inventario Metco tal cual (.xls o .xlsx: se compara en el momento con
        Tango, igual que Stock > Comparar con inventario Excel) o el Excel de esa comparación ya hecha.
        No cambia ningún conteo."""
        filas = _filas_comparacion(contenido)
        origen = "comparación"
        if filas is None:
            if servicio is None:
                raise PedidoInvalido("Ese Excel no es ni el inventario ni la comparación de inventario.")
            from . import inventario
            try:
                filas = inventario.comparar(contenido, servicio, nombre_archivo)["filas"]
            except inventario.InventarioInvalido as e:
                raise PedidoInvalido(str(e)) from None
            origen = "inventario"
        ref: dict[str, dict] = {}
        no_en_tango = 0
        for f in filas:
            codigo = str(f.get("codigo_tango") or "").strip()
            estado = str(f.get("estado") or "").strip()
            if not codigo:
                no_en_tango += estado == "No está en Tango"
                continue
            x = ref.setdefault(codigo, {"excel": None, "ubicacion": "", "estado": "", "diferencia": None,
                                        "cantidad_excel": None, "unidad_excel": "", "notas": ""})
            if estado and (not x["estado"] or estado in ESTADOS_DIFERENCIA):
                x["estado"] = estado
            if estado in ESTADOS_DIFERENCIA and isinstance(f.get("diferencia"), (int, float)):
                x["diferencia"] = round(float(f["diferencia"]), 4)
            if isinstance(f.get("excel_en_unidad_tango"), (int, float)):
                x["excel"] = round((x["excel"] or 0) + float(f["excel_en_unidad_tango"]), 4)
            if isinstance(f.get("cantidad_excel"), (int, float)) and estado != "Solo en Tango":
                x["cantidad_excel"] = round((x["cantidad_excel"] or 0) + float(f["cantidad_excel"]), 4)
                x["unidad_excel"] = x["unidad_excel"] or str(f.get("unidad_excel") or "")
            for campo in ("ubicacion", "notas"):
                t = str(f.get(campo) or "").strip()
                if t and t not in x[campo]:
                    x[campo] = ("; " if campo == "notas" else ", ").join(filter(None, [x[campo], t]))[:300]
        if not ref:
            raise PedidoInvalido("No encontré artículos con código de Tango en ese Excel.")
        with self._lock:
            datos = self._leer()
            r = self._buscar(datos, id_recuento)
            r["referencia"] = ref
            r["referencia_cargada"] = datetime.now().isoformat(timespec="seconds")
            r["referencia_archivo"] = (nombre_archivo or "")[:120]
            self._guardar(datos)
        return {"articulos": len(ref), "origen": origen, "no_en_tango": no_en_tango,
                "con_diferencia": sum(1 for x in ref.values() if x["estado"] in ESTADOS_DIFERENCIA)}

    # ------------------------------------------------------------ salidas
    def diferencias(self, id_recuento: int) -> list[dict]:
        r = self.uno(id_recuento)
        filas = []
        for c in r["conteos"].values():
            dif = round(c["cantidad"] - c["tango"], 4)
            if abs(dif) > EPS:
                filas.append({**c, "diferencia": dif})
        return sorted(filas, key=lambda x: (x["codigo"], x["partida"]))

    def excel(self, id_recuento: int) -> bytes:
        r = self.uno(id_recuento)
        ref = r.get("referencia") or {}
        cols = [("Artículo", "texto"), ("Descripción", "texto"), ("Partida", "texto"), ("Unidad", "texto"),
                ("Tango al contar", "numero"), ("Contado", "numero"), ("Diferencia", "numero"),
                ("Lote nuevo", "texto"), ("Nota", "texto"), ("Contó", "texto"), ("Cuándo", "texto"),
                ("Excel inventario (artículo)", "numero"), ("Ubicación", "texto"), ("Comparación con el Excel", "texto")]
        filas = [[c["codigo"], c.get("descripcion", ""), c["partida"], c.get("unidad", ""), c["tango"], c["cantidad"],
                  round(c["cantidad"] - c["tango"], 4), "Sí" if c.get("nueva") else "", c.get("nota", ""), c.get("quien", ""),
                  c.get("cuando", "").replace("T", " "),
                  (ref.get(c["codigo"]) or {}).get("excel"), (ref.get(c["codigo"]) or {}).get("ubicacion", ""),
                  (ref.get(c["codigo"]) or {}).get("estado", "")]
                 for c in sorted(r["conteos"].values(), key=lambda x: (x["codigo"], x["partida"]))]
        dif = [f for f in filas if abs(f[6]) > EPS]
        return xlsx.escribir_libro([("Diferencias", cols, dif), ("Todo lo contado", cols, filas)])

    def planilla_ajuste(self, id_recuento: int, plantilla: Path | None = None) -> bytes:
        plantilla = plantilla or ruta_plantilla()
        if not plantilla.exists():
            raise PedidoInvalido("Falta la plantilla de Ajustes de stock de Tango: cargala una vez desde esta pantalla.")
        filas = self.diferencias(id_recuento)
        if not filas:
            raise PedidoInvalido("No hay diferencias: no hace falta ajustar nada.")
        return armar_planilla_ajuste(filas, plantilla)


def _filas_comparacion(contenido: bytes) -> list[dict] | None:
    """Filas del Excel de "Comparación de inventario" (hoja Todo). None si el archivo no es eso."""
    try:
        hojas = xlsx.leer(contenido)
    except xlsx.ExcelInvalido:
        return None                          # un .xls (el inventario) cae aca
    filas = hojas.get("Todo") or []
    if not filas:
        return None
    enc = [_sin_acentos(str(x or "")) for x in filas[0]]
    def col(nombre):
        return next((i for i, t in enumerate(enc) if t == nombre), None)
    columnas = {"estado": col("estado"), "codigo_tango": col("codigo tango"), "excel_en_unidad_tango": col("excel en unidad de tango"),
                "ubicacion": col("ubicacion"), "cantidad_excel": col("cantidad excel"), "unidad_excel": col("unidad excel"),
                "notas": col("notas"), "diferencia": next((i for i, t in enumerate(enc) if t.startswith("diferencia")), None)}
    if columnas["codigo_tango"] is None or columnas["excel_en_unidad_tango"] is None:
        return None
    salida = []
    for f in filas[1:]:
        salida.append({k: (f[i] if i is not None and i < len(f) else None) for k, i in columnas.items()})
    return salida


# ---------------------------------------------------------------- plantilla de Tango
# Plantilla de "Ajustes de stock" masivos (Stock > Movimientos masivos > Ajustes de stock > Exportar
# plantilla vacia). Hoja visible "Ajustes de Stock": Codigo, Descripcion, Tipo de movimiento
# (Entrada/Salida), Deposito (" 1", con espacio: con "1" Tango dice "Deposito inexistente"),
# Informar partida (Si/No), Numero partida, Vencimiento partida, Unidad medida, Cantidad (siempre
# positiva), Unidad medida 2, Cantidad 2, Precio, Error. Las columnas se buscan por el encabezado.
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# dato -> nombres posibles del encabezado (sin acentos, en minuscula; el primero que contenga alguno)
_COLUMNAS = [
    ("codigo", ("codigo",)),
    ("descripcion", ("descripcion",)),
    ("tipo", ("tipo de movimiento", "tipo mov", "tipo")),
    ("deposito", ("deposito",)),
    ("informa", ("informa",)),
    ("partida", ("numero partida", "numero de partida", "nro. partida", "nro partida", "partida")),
    ("unidad", ("unidad",)),
    ("cantidad", ("cantidad",)),
]
OBLIGATORIAS = ("codigo", "tipo", "cantidad")


def _sin_acentos(t: str) -> str:
    return " ".join((t or "").lower().translate(str.maketrans("áéíóúü", "aeiouu")).split())


def _hojas(z: zipfile.ZipFile) -> list[tuple[str, str, str]]:
    """[(nombre, estado, ruta del xml)] en el orden del libro."""
    import xml.etree.ElementTree as ET
    libro = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    destino = {r.get("Id"): r.get("Target") for r in rels}
    salida = []
    for h in libro.iter("{%s}sheet" % _NS["m"]):
        rid = h.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        t = (destino.get(rid) or "").lstrip("/")
        salida.append((h.get("name"), h.get("state") or "visible", t if t.startswith("xl/") else "xl/" + t))
    return salida


def _encabezado(z: zipfile.ZipFile, ruta_hoja: str) -> dict[str, str]:
    """{letra de columna: texto} de la fila 1, en orden de columna."""
    import xml.etree.ElementTree as ET
    compartidos = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter("{%s}si" % _NS["m"]):
            compartidos.append("".join(t.text or "" for t in si.iter("{%s}t" % _NS["m"])))
    hoja = ET.fromstring(z.read(ruta_hoja))
    salida = {}
    for c in hoja.iter("{%s}c" % _NS["m"]):
        ref = c.get("r") or ""
        if re.sub(r"[A-Z]+", "", ref) != "1":
            continue
        v = c.find("m:v", _NS)
        if c.get("t") == "s" and v is not None:
            texto = compartidos[int(v.text)]
        else:
            texto = "".join(t.text or "" for t in c.iter("{%s}t" % _NS["m"])) or (v.text if v is not None else "")
        salida[re.sub(r"\d+", "", ref)] = texto or ""
    return dict(sorted(salida.items(), key=lambda x: _orden_columna(x[0])))


def _mapear(enc: dict[str, str]) -> dict[str, str]:
    mapa: dict[str, str] = {}
    for dato, nombres in _COLUMNAS:
        for letra, texto in enc.items():
            t = _sin_acentos(texto)
            if letra not in mapa.values() and any(n in t for n in nombres):
                mapa[dato] = letra
                break
    return mapa


def describir_plantilla(contenido: bytes) -> dict:
    """Valida una plantilla de Ajustes de stock y devuelve que columna es cada dato."""
    try:
        z = zipfile.ZipFile(io.BytesIO(contenido))
        hojas = _hojas(z)
    except (zipfile.BadZipFile, KeyError):
        raise PedidoInvalido("Eso no es un Excel (.xlsx). Bajá la plantilla desde Ajustes de stock en Tango.") from None
    if not any(n == "_metadata" for n, _, _ in hojas):
        raise PedidoInvalido("Esa planilla no es una plantilla de Tango (le falta la hoja de control _metadata).")
    vistos = []
    for nombre, estado, ruta in hojas:
        if estado != "visible" or ruta not in z.namelist():
            continue
        enc = _encabezado(z, ruta)
        mapa = _mapear(enc)
        if all(d in mapa for d in OBLIGATORIAS):
            return {"hoja": nombre, "ruta": ruta, "columnas": mapa, "encabezados": enc}
        vistos.append(nombre)
    raise PedidoInvalido("Esa no es la plantilla de Ajustes de stock: no tiene la columna «Tipo de movimiento». "
                         "En Tango: Stock > Movimientos masivos > Ajustes de stock > Exportar plantilla vacía.")


def _orden_columna(letra: str) -> int:
    n = 0
    for ch in letra:
        n = n * 26 + ord(ch) - 64
    return n


def _estilos_columnas(xml: str) -> dict[int, str]:
    """Estilo de cada columna segun <cols> (asi la celda queda con el formato que trae la plantilla)."""
    estilos = {}
    for m in re.finditer(r"<col\b([^>]*)/?>", xml):
        a = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        if a.get("style") and a.get("min", "").isdigit() and a.get("max", "").isdigit():
            for i in range(int(a["min"]), min(int(a["max"]), 200) + 1):
                estilos[i] = a["style"]
    return estilos


def _celda(ref: str, valor, estilo: str | None) -> str:
    s = f' s="{estilo}"' if estilo else ""
    if isinstance(valor, (int, float)):
        texto = f"{valor:.4f}".rstrip("0").rstrip(".")
        return f'<c r="{ref}"{s}><v>{texto}</v></c>'
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{escape(str(valor))}</t></is></c>'


def renglon_ajuste(f: dict) -> dict:
    """Diferencia (contado - Tango) -> renglon de la plantilla: entrada o salida con cantidad positiva."""
    return {"codigo": f["codigo"], "descripcion": f.get("descripcion", ""),
            "tipo": "Entrada" if f["diferencia"] > 0 else "Salida", "deposito": " 1",
            "informa": "Si" if f["partida"] else "No", "partida": f["partida"], "unidad": f.get("unidad", ""),
            "cantidad": round(abs(f["diferencia"]), 4)}


def armar_planilla_ajuste(filas: list[dict], plantilla: Path) -> bytes:
    """Copia la plantilla de Tango tal cual (hojas ocultas y _metadata incluidas) y agrega un renglon
    por diferencia en la hoja de ajustes. Solo se reescribe el xml de esa hoja."""
    contenido = plantilla.read_bytes()
    info = describir_plantilla(contenido)
    col = info["columnas"]
    salida = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(contenido)) as origen, zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as destino:
        for item in origen.infolist():
            datos = origen.read(item.filename)
            if item.filename == info["ruta"]:
                xml = datos.decode("utf-8")
                if "</sheetData>" not in xml and "<sheetData/>" not in xml:
                    raise PedidoInvalido("La plantilla de ajustes no tiene la forma esperada.")
                estilos = _estilos_columnas(xml)
                xml_filas = []
                for n, f in enumerate(filas, start=2):
                    valores = renglon_ajuste(f)
                    celdas = sorted(((col[d], v) for d, v in valores.items() if d in col and v not in ("", None)),
                                    key=lambda x: _orden_columna(x[0]))
                    xml_filas.append(f'<row r="{n}">' + "".join(
                        _celda(f"{letra}{n}", v, estilos.get(_orden_columna(letra))) for letra, v in celdas) + "</row>")
                xml = xml.replace("<sheetData/>", "<sheetData></sheetData>", 1)
                # fuera las filas de ejemplo que pudiera traer (queda solo el encabezado)
                xml = re.sub(r'<row r="(?!1")\d+"[^>]*?(?:/>|>.*?</row>)', "", xml, flags=re.S)
                ultima = max([_orden_columna(x) for x in info["encabezados"]] + [1])
                letra_ult = next((k for k in info["encabezados"] if _orden_columna(k) == ultima), "A")
                xml = re.sub(r'<dimension ref="[^"]*"/>', f'<dimension ref="A1:{letra_ult}{len(filas) + 1}"/>', xml, count=1)
                xml = xml.replace("</sheetData>", "".join(xml_filas) + "</sheetData>", 1)
                datos = xml.encode("utf-8")
            destino.writestr(item, datos)
    return salida.getvalue()
