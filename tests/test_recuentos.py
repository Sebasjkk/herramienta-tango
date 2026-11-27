"""
Recuentos de stock: conteos por lote, diferencias y planilla de Ajustes de stock.
La plantilla de Ajustes se simula con la de Egresos (misma forma, hoja oculta _metadata)
cambiandole los encabezados por los de Ajustes; todo lo que no es esa hoja tiene que quedar
identico, byte a byte.
"""

import io
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from herramienta_tango import xlsx
from herramienta_tango.mezclas import PLANTILLA as PLANTILLA_EGRESO
from herramienta_tango.precios import PedidoInvalido
from herramienta_tango.recuentos import Recuentos, armar_planilla_ajuste, describir_plantilla

ENCABEZADOS = ["Código", "Descripción", "Tipo de movimiento", "Depósito", "Informar partida", "Número partida",
               "Vencimiento partida", "Unidad medida", "Cantidad", "Unidad medida 2", "Cantidad 2", "Precio", "Error"]


def plantilla_ajuste(con_ejemplo=True) -> bytes:
    salida = io.BytesIO()
    with zipfile.ZipFile(PLANTILLA_EGRESO) as a, zipfile.ZipFile(salida, "w") as b:
        for item in a.infolist():
            datos = a.read(item.filename)
            if item.filename == "xl/worksheets/sheet2.xml":
                celdas = "".join(f'<c r="{chr(65 + i)}1" t="inlineStr"><is><t>{h}</t></is></c>' for i, h in enumerate(ENCABEZADOS))
                ejemplo = '<row r="2"><c r="A2" t="inlineStr"><is><t>EJEMPLO</t></is></c></row>' if con_ejemplo else ""
                xml = re.sub(r"<sheetData>.*?</sheetData>|<sheetData/>", f'<sheetData><row r="1">{celdas}</row>{ejemplo}</sheetData>',
                             datos.decode(), flags=re.S)
                datos = xml.encode()
            b.writestr(item, datos)
    return salida.getvalue()


class TestRecuentos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = Recuentos(Path(self.tmp.name) / "recuentos.json")
        self.id = self.reg.crear("Recuento diciembre", "Gustavo (10.0.0.5)")["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_crear_pide_nombre(self):
        with self.assertRaises(PedidoInvalido):
            self.reg.crear("  ", "x")

    def test_conteos_y_diferencias(self):
        self.reg.contar(self.id, "4000514", "L1", 100, 120, "G", unidad="KG")
        self.reg.contar(self.id, "4000514", "L2", "5,5", 5.5, "G", unidad="KG")       # coincide
        self.reg.contar(self.id, "1000100", "HIST-PO000", 3, 0, "G", unidad="UNI", nueva=True)
        self.reg.contar(self.id, "SINPART", "", 2, -3, "G", unidad="UNI")              # Tango negativo
        difs = {(d["codigo"], d["partida"]): d["diferencia"] for d in self.reg.diferencias(self.id)}
        self.assertEqual(difs, {("4000514", "L1"): -20.0, ("1000100", "HIST-PO000"): 3.0, ("SINPART", ""): 5.0})
        r = self.reg.todos()[0]
        self.assertEqual((r["contados"], r["con_diferencia"]), (4, 3))
        self.assertNotIn("conteos", r)

    def test_recontar_reemplaza_y_vacio_borra(self):
        self.reg.contar(self.id, "A", "L1", 10, 12, "G")
        self.reg.contar(self.id, "A", "L1", 11, 11, "G")    # recuento mas tarde: nueva foto de Tango
        self.assertEqual(self.reg.diferencias(self.id), [])
        self.reg.contar(self.id, "A", "L1", "", 11, "G")
        self.assertEqual(self.reg.uno(self.id)["conteos"], {})

    def test_cantidad_invalida(self):
        for mal in ("-1", "abc"):
            with self.assertRaises(PedidoInvalido):
                self.reg.contar(self.id, "A", "L1", mal, 0, "G")

    def test_cerrado_no_deja_contar_y_se_reabre(self):
        self.reg.cambiar_estado(self.id, "cerrado", "G")
        with self.assertRaises(PedidoInvalido):
            self.reg.contar(self.id, "A", "L1", 1, 0, "G")
        self.reg.cambiar_estado(self.id, "abierto", "G")
        self.reg.contar(self.id, "A", "L1", 1, 0, "G")

    def test_borrar_pide_el_nombre(self):
        with self.assertRaises(PedidoInvalido):
            self.reg.borrar(self.id, "otro")
        self.reg.borrar(self.id, "recuento DICIEMBRE")
        self.assertEqual(self.reg.todos(), [])

    def test_excel_del_recuento(self):
        self.reg.contar(self.id, "A", "L1", 10, 12, "G")
        self.reg.contar(self.id, "B", "", 1, 1, "G")
        hojas = xlsx.leer(self.reg.excel(self.id))
        self.assertEqual(len(hojas["Diferencias"]), 2)
        self.assertEqual(len(hojas["Todo lo contado"]), 3)

    def test_referencia_desde_la_comparacion(self):
        comp = xlsx.escribir_libro([("Todo", [("Código Tango", "texto"), ("Excel en unidad de Tango", "numero"), ("Ubicación", "texto")],
                                     [["A", 5.0, "Lab"], ["A", 2.0, "Galpón"], ["B", None, ""]])])
        self.assertEqual(self.reg.cargar_referencia(self.id, comp), {"articulos": 2})
        ref = self.reg.uno(self.id)["referencia"]
        self.assertEqual(ref["A"], {"excel": 7.0, "ubicacion": "Lab, Galpón"})
        self.assertIsNone(ref["B"]["excel"])
        with self.assertRaises(PedidoInvalido):
            self.reg.cargar_referencia(self.id, xlsx.escribir([("Otra", "texto")], [["x"]]))


class TestPlantillaAjuste(unittest.TestCase):
    def test_reconoce_columnas(self):
        info = describir_plantilla(plantilla_ajuste())
        self.assertEqual(info["columnas"], {"codigo": "A", "descripcion": "B", "tipo": "C", "deposito": "D", "informa": "E",
                                            "partida": "F", "unidad": "H", "cantidad": "I"})

    def test_rechaza_la_de_egresos_y_otros_archivos(self):
        with self.assertRaises(PedidoInvalido):
            describir_plantilla(PLANTILLA_EGRESO.read_bytes())
        with self.assertRaises(PedidoInvalido):
            describir_plantilla(b"no es un zip")
        with self.assertRaises(PedidoInvalido):
            describir_plantilla(xlsx.escribir([(h, "texto") for h in ENCABEZADOS], []))   # sin _metadata

    def test_planilla(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = Path(d) / "p.xlsx"
            ruta.write_bytes(plantilla_ajuste())
            filas = [{"codigo": "4000514", "descripcion": "Polvo", "partida": "L1", "unidad": "KG", "diferencia": -20.0},
                     {"codigo": "1000100", "partida": "HIST-PO000", "unidad": "UNI", "diferencia": 3.0},
                     {"codigo": "SINPART", "partida": "", "unidad": "UNI", "diferencia": 5.0}]
            contenido = armar_planilla_ajuste(filas, ruta)
            hoja = xlsx.leer(contenido)["Artículos y partidas"]
            self.assertEqual(hoja[0], ENCABEZADOS)
            self.assertEqual(hoja[1][:9], ["4000514", "Polvo", "Salida", " 1", "Si", "L1", None, "KG", 20.0])
            self.assertEqual(hoja[2][:9], ["1000100", None, "Entrada", " 1", "Si", "HIST-PO000", None, "UNI", 3.0])
            self.assertEqual(hoja[3][:9], ["SINPART", None, "Entrada", " 1", "No", None, None, "UNI", 5.0])
            self.assertEqual(len(hoja), 4)                       # la fila de ejemplo de la plantilla no queda
            with zipfile.ZipFile(io.BytesIO(contenido)) as nuevo, zipfile.ZipFile(ruta) as original:
                for n in original.namelist():
                    if n != "xl/worksheets/sheet2.xml":
                        self.assertEqual(nuevo.read(n), original.read(n), n)

    def test_sin_plantilla_o_sin_diferencias(self):
        with tempfile.TemporaryDirectory() as d:
            reg = Recuentos(Path(d) / "r.json")
            i = reg.crear("R", "x")["id"]
            with self.assertRaises(PedidoInvalido):
                reg.planilla_ajuste(i, Path(d) / "no-esta.xlsx")
            ruta = Path(d) / "p.xlsx"
            ruta.write_bytes(plantilla_ajuste(False))
            reg.contar(i, "A", "L1", 2, 2, "x")
            with self.assertRaises(PedidoInvalido):
                reg.planilla_ajuste(i, ruta)


if __name__ == "__main__":
    unittest.main()
