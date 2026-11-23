"""
Lector y escritor minimos de .xlsx con la biblioteca estandar (la Herramienta no instala paquetes).

leer(contenido) -> {"Nombre de hoja": [[celda, ...], ...]}
Las celdas vienen como str, float, bool o None. Las fechas quedan como el numero
de serie de Excel (no se usan para nada en la Herramienta).
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
MAX_FILAS = 20000


class ExcelInvalido(ValueError):
    pass


def _columna(ref: str) -> int:
    letras = re.match(r"[A-Z]+", ref or "")
    n = 0
    for ch in (letras.group(0) if letras else "A"):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _texto(nodo) -> str:
    return "".join(t.text or "" for t in nodo.iter(f"{{{NS['x']}}}t"))


def leer(contenido: bytes) -> dict[str, list[list]]:
    try:
        z = zipfile.ZipFile(io.BytesIO(contenido))
        libro = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError):
        raise ExcelInvalido("El archivo no es un Excel (.xlsx) válido.") from None

    destinos = {r.get("Id"): r.get("Target") for r in rels.findall("rel:Relationship", NS)}
    compartidos: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        compartidos = [_texto(si) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("x:si", NS)]

    hojas = {}
    for h in libro.findall("x:sheets/x:sheet", NS):
        destino = destinos.get(h.get(f"{{{NS['r']}}}id"), "")
        ruta = destino.lstrip("/") if destino.startswith("/") else posixpath.normpath(posixpath.join("xl", destino))
        try:
            hoja = ET.fromstring(z.read(ruta))
        except (KeyError, ET.ParseError):
            continue
        filas = []
        for fila in hoja.iter(f"{{{NS['x']}}}row"):
            if len(filas) > MAX_FILAS:
                raise ExcelInvalido(f"La hoja {h.get('name')} tiene demasiadas filas.")
            n = int(fila.get("r") or len(filas) + 1) - 1
            while len(filas) < n:
                filas.append([])
            valores: list = []
            for c in fila.findall("x:c", NS):
                col = _columna(c.get("r"))
                tipo = c.get("t")
                v = c.find("x:v", NS)
                if tipo == "s" and v is not None:
                    valor = compartidos[int(v.text)]
                elif tipo == "inlineStr":
                    valor = _texto(c)
                elif tipo == "str":
                    valor = v.text if v is not None else ""
                elif tipo == "b" and v is not None:
                    valor = v.text == "1"
                elif v is not None and v.text not in (None, ""):
                    try:
                        valor = float(v.text)
                    except ValueError:
                        valor = v.text
                else:
                    valor = None
                while len(valores) <= col:
                    valores.append(None)
                valores[col] = valor
            filas.append(valores)
        hojas[h.get("name")] = filas
    return hojas


# ------------------------------------------------------------------ escribir
# Planilla simple de una hoja: encabezado en negrita, filtro, primera fila fija y
# anchos de columna segun el contenido. Para exportar lo que se ve en pantalla.

MAX_FILAS_EXPORTAR = 50000
_INVALIDOS_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _letra(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _esc(texto: str) -> str:
    texto = _INVALIDOS_XML.sub("", texto)
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def escribir(columnas: list[tuple[str, str]], filas: list[list], hoja: str = "Datos") -> bytes:
    """columnas: [(titulo, "texto" | "numero")]. Devuelve el .xlsx."""
    if len(filas) > MAX_FILAS_EXPORTAR:
        raise ValueError(f"Son demasiadas filas para exportar (máximo {MAX_FILAS_EXPORTAR}).")
    anchos = [min(60, max(10, len(t) + 2)) for t, _ in columnas]
    xml_filas = []
    celdas = [f'<c r="{_letra(i)}1" t="inlineStr" s="1"><is><t>{_esc(str(t))}</t></is></c>' for i, (t, _) in enumerate(columnas)]
    xml_filas.append(f'<row r="1">{"".join(celdas)}</row>')
    for n, fila in enumerate(filas, start=2):
        celdas = []
        for i, (_, tipo) in enumerate(columnas):
            v = fila[i] if i < len(fila) else None
            if v is None or v == "":
                continue
            ref = f"{_letra(i)}{n}"
            if tipo == "numero" and isinstance(v, (int, float)) and not isinstance(v, bool):
                celdas.append(f'<c r="{ref}" s="2"><v>{v!r}</v></c>')
                anchos[i] = max(anchos[i], min(18, len(f"{v:,.2f}") + 2))
            else:
                t = str(v)
                celdas.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_esc(t)}</t></is></c>')
                anchos[i] = max(anchos[i], min(60, len(t) + 2))
        xml_filas.append(f'<row r="{n}">{"".join(celdas)}</row>')
    ultima = f"{_letra(len(columnas) - 1)}{max(1, len(filas) + 1)}"
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{a}" customWidth="1"/>' for i, a in enumerate(anchos))
    hoja_xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                '</sheetView></sheetViews>'
                f'<cols>{cols}</cols><sheetData>{"".join(xml_filas)}</sheetData>'
                f'<autoFilter ref="A1:{ultima}"/></worksheet>')
    nombre_hoja = _esc(re.sub(r"[\[\]:*?/\\]", " ", hoja)[:31] or "Datos")
    archivos = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{nombre_hoja}" sheetId="1" r:id="rId1"/></sheets>'
            f'<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">\'{nombre_hoja}\'!$A$1:${_letra(len(columnas) - 1)}${max(1, len(filas) + 1)}</definedName></definedNames>'
            '</workbook>',
        "xl/_rels/workbook.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>',
        "xl/styles.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/></numFmts>'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
            '<fill><patternFill patternType="solid"><fgColor rgb="FFDCEFED"/></patternFill></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
            '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>',
        "xl/worksheets/sheet1.xml": hoja_xml,
    }
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return salida.getvalue()
