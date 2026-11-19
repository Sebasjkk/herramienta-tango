"""
Lector minimo de .xlsx con la biblioteca estandar (la Herramienta no instala paquetes).

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
