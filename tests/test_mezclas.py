"""
Mezclas de polvos: validaciones, historial y planilla de Egresos de Stock.
La planilla se arma sobre la plantilla original de Tango (19/11/2026) y todo lo
que no es la hoja de renglones tiene que quedar idéntico, byte a byte.
"""

import io
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from herramienta_tango.mezclas import PLANTILLA, EditorMezclas, RegistroMezclas, armar_planilla
from herramienta_tango.precios import PedidoInvalido
from herramienta_tango.tango.modelos import Articulo, Deposito, SaldoPartida

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def articulo(codigo, desc, partidas=True, unidad="KG"):
    return Articulo(1, codigo, desc, "", "", "", partidas, True, "", unidad, "", 0, 0, 0)


def saldo(codigo, partida, kg, deposito="CENTRAL"):
    return SaldoPartida(1, codigo, "", deposito, partida, "", None, "KG", kg)


class ServicioFalso:
    def articulos(self, forzar=False):
        return [articulo("1000089", "METCO 450NS"), articulo("1000051", "METCOLOY 5 1/8"),
                articulo("1000100", "AMDRY 1/8"), articulo("1PAR00001", "O'RING", partidas=False, unidad="UNI")], 0

    def saldos_por_partida(self, forzar=False):
        return [saldo("1000089", "2120564", 30), saldo("1000051", "HIST-PO000", 12),
                saldo("1000100", "L9", 5, "MAQUINARIAS-BIENES DE USO")], 0

    def depositos(self, forzar=False):
        return [Deposito(1, "1", "CENTRAL", "", False), Deposito(5, "5", "MAQUINARIAS-BIENES DE USO", "", False)], 0


class TestMezclas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.editor = EditorMezclas(ServicioFalso(), RegistroMezclas(Path(self.tmp.name) / "mezclas.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def crear(self, renglones, referencia="Remito 0001-00001234 · SCIPIO"):
        return self.editor.crear(referencia, renglones, "Gustavo (10.0.0.5)")

    def test_mezcla_de_tres_polvos(self):
        m = self.crear([{"articulo": "1000089", "partida": "2120564", "cantidad": "3,5"},
                        {"articulo": "1000051", "partida": "HIST-PO000", "cantidad": 1.5},
                        {"articulo": "1000100", "partida": "L9", "cantidad": "0.25"}])
        self.assertEqual(m["id"], 1)
        self.assertEqual(m["estado"], "pendiente")
        self.assertEqual([r["cantidad"] for r in m["renglones"]], [3.5, 1.5, 0.25])
        self.assertEqual([r["deposito"] for r in m["renglones"]], [" 1", " 1", " 5"])   # de donde esta la partida
        self.assertEqual(self.editor.registro.todas()[0]["referencia"], "Remito 0001-00001234 · SCIPIO")

    def test_validaciones(self):
        casos = [
            ([], "Agregá"),
            ([{"articulo": "9999", "partida": "x", "cantidad": 1}], "elegí un artículo"),
            ([{"articulo": "1000089", "partida": "", "cantidad": 1}], "elegí la partida"),
            ([{"articulo": "1000089", "partida": "NO-EXISTE", "cantidad": 1}], "no figura"),
            ([{"articulo": "1000089", "partida": "2120564", "cantidad": "0"}], "mayor que cero"),
            ([{"articulo": "1000089", "partida": "2120564", "cantidad": "abc"}], "no es un número"),
            ([{"articulo": "1000089", "partida": "2120564", "cantidad": 1},
              {"articulo": "1000089", "partida": "2120564", "cantidad": 2}], "dos veces"),
        ]
        for renglones, texto in casos:
            with self.subTest(texto=texto), self.assertRaisesRegex(PedidoInvalido, texto):
                self.crear(renglones)
        with self.assertRaisesRegex(PedidoInvalido, "remito o el cliente"):
            self.crear([{"articulo": "1000089", "partida": "2120564", "cantidad": 1}], referencia="  ")

    def test_subir_y_borrar(self):
        a = self.crear([{"articulo": "1000089", "partida": "2120564", "cantidad": 1}])
        b = self.crear([{"articulo": "1PAR00001", "cantidad": 2}])
        self.editor.marcar_subidas([a["id"]], "Estela")
        with self.assertRaisesRegex(PedidoInvalido, "ya se subió"):
            self.editor.borrar(a["id"], "Estela")
        self.editor.borrar(b["id"], "Estela")
        todas = self.editor.registro.todas()
        self.assertEqual([(m["id"], m["estado"], m.get("subida_por")) for m in todas], [(1, "subida", "Estela")])

    def test_planilla_respeta_la_plantilla(self):
        self.crear([{"articulo": "1000089", "partida": "2120564", "cantidad": 3.5},
                    {"articulo": "1PAR00001", "cantidad": 2}])
        self.crear([{"articulo": "1000051", "partida": "HIST-PO000", "cantidad": 1}])
        nombre, contenido = self.editor.planilla([1, 2])
        self.assertEqual(nombre, "Egreso_mezcla_1-2.xlsx")
        original, nuevo = zipfile.ZipFile(PLANTILLA), zipfile.ZipFile(io.BytesIO(contenido))
        self.assertEqual(original.namelist(), nuevo.namelist())
        for n in original.namelist():
            if n != "xl/worksheets/sheet2.xml":
                self.assertEqual(original.read(n), nuevo.read(n), n)     # _metadata y demas, intactos
        hoja = ET.fromstring(nuevo.read("xl/worksheets/sheet2.xml"))
        filas = hoja.findall(".//x:sheetData/x:row", NS)
        self.assertEqual(len(filas), 4)                                   # encabezado + 3 renglones

        def valores(fila):
            out = {}
            for c in fila.findall("x:c", NS):
                t = c.find("x:is/x:t", NS)
                out[c.get("r")[0]] = t.text if t is not None else c.find("x:v", NS).text
            return out
        self.assertEqual(valores(filas[1]), {"A": "1000089", "B": "METCO 450NS", "C": " 1", "D": "Si",
                                             "E": "2120564", "F": "KG", "G": "3.5"})
        self.assertEqual(valores(filas[2]), {"A": "1PAR00001", "B": "O'RING", "C": " 1", "D": "No", "F": "UNI", "G": "2"})
        self.assertEqual(valores(filas[3])["E"], "HIST-PO000")
        self.assertEqual(hoja.find("x:dimension", NS).get("ref"), "A1:K4")

    def test_planilla_se_abre_con_openpyxl(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl no esta instalado")
        contenido = armar_planilla([{"codigo": "1000089", "descripcion": "Ñandú & <cía>", "partida": "P1",
                                     "deposito": " 1", "unidad": "KG", "cantidad": 2.125}])
        wb = openpyxl.load_workbook(io.BytesIO(contenido))
        self.assertEqual([s.sheet_state for s in wb], ["veryHidden", "visible", "visible", "veryHidden"])
        fila = [c.value for c in wb["Artículos y partidas"][2]][:7]
        self.assertEqual(fila, ["1000089", "Ñandú & <cía>", " 1", "Si", "P1", "KG", 2.125])


if __name__ == "__main__":
    unittest.main()
