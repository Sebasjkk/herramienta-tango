"""
Importar listas de precios desde Excel: lector de .xlsx, vista previa y carga,
contra el Tango falso de las pruebas de precios.
"""

import io
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from herramienta_tango import xlsx
from herramienta_tango.importar_listas import ImportadorListas
from herramienta_tango.precios import EditorPrecios, PedidoInvalido, RegistroCambios
from herramienta_tango.tango.modelos import Cliente
from test_precios import ServicioFalso, TangoFalso


def excel(hojas: dict) -> bytes:
    """Arma un .xlsx minimo (textos en linea, numeros como numeros)."""
    def celda(ref, v):
        if v is None:
            return ""
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        nombres = list(hojas)
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
                   "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(nombres, 1)) +
                   "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
                   "".join(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="x"/>' for i in range(1, len(nombres) + 1)) +
                   "</Relationships>")
        for i, n in enumerate(nombres, 1):
            filas = "".join(f'<row r="{f}">' + "".join(celda(f"{chr(65 + c)}{f}", v) for c, v in enumerate(fila)) + "</row>"
                            for f, fila in enumerate(hojas[n], 1))
            z.writestr(f"xl/worksheets/sheet{i}.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       f"<sheetData>{filas}</sheetData></worksheet>")
    return buf.getvalue()


CABECERA = ["Lista", "Cliente", "Razón social", "Artículo", "Descripción", "UM", "Precio USD", "Cargar",
            "Precio corregido (Fran)", "Observaciones"]
LIBRO = {
    "Resumen": [["Concepto", "Valor"], ["Clientes", 2]],
    "Listas": [["Nro lista", "Descripción", "Cliente"], [10, "SCIPIO", "SCIPIO"], [24, "AERARG", "AERARG"]],
    "Precios por cliente": [
        CABECERA,
        [10, "SCIPIO", "", "0039812", "BELT", "UNI", 241.78, "SÍ", None, None],          # ya esta igual
        [10, "SCIPIO", "", "0039813", "BELT", "UNI", 241.78, "SÍ", 250, "precio viejo"],  # corregido -> distinto
        [10, "SCIPIO", "", "1000125", "POLVO", "KG", 99.5, "SÍ", None, None],             # agregar
        [10, "SCIPIO", "", "9999999", "NO EXISTE", "KG", 10, "SÍ", None, None],           # error
        [24, "AERARG", "", "1PAR00001", "ORING", "UNI", "12,5", "SÍ", None, None],        # lista nueva
        [24, "AERARG", "", "0039812", "BELT", "UNI", 0, "NO", None, "PRECIO 0"],          # no cargar
    ],
}


class TestLectorExcel(unittest.TestCase):
    def test_lee_hojas(self):
        h = xlsx.leer(excel(LIBRO))
        self.assertEqual(list(h), ["Resumen", "Listas", "Precios por cliente"])
        self.assertEqual(h["Precios por cliente"][1][:4], [10.0, "SCIPIO", "", "0039812"])
        self.assertEqual(len(h["Precios por cliente"][1]), 8)          # las vacias del final no se guardan

    def test_archivo_invalido(self):
        with self.assertRaises(xlsx.ExcelInvalido):
            xlsx.leer(b"no es un excel")


class TestImportador(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tango = TangoFalso()
        clientes = [Cliente(id=660, codigo="SCIPIO", razon_social="AMG SCIPIONI", cuit="", habilitado=True, lista_precios="SCIPIO"),
                    Cliente(id=309, codigo="AERARG", razon_social="AEROLINEAS ARG", cuit="", habilitado=True, lista_precios="METCO")]
        self.servicio = ServicioFalso(clientes)
        self.editor = EditorPrecios(self.tango, self.servicio, RegistroCambios(Path(self.tmp.name) / "c.jsonl"))
        self.imp = ImportadorListas(self.editor, self.servicio)

    def tearDown(self):
        self.tmp.cleanup()

    def esperar(self):
        for _ in range(200):
            if not self.imp.estado()["corriendo"]:
                return self.imp.estado()
            time.sleep(0.02)
        self.fail("La importación no terminó")

    def test_vista_previa_no_escribe(self):
        plan = self.imp.analizar(excel(LIBRO))
        self.assertEqual(self.tango.escrituras, [])
        scipio, aerarg = plan["listas"]
        self.assertEqual([r["estado"] for r in scipio["renglones"]], ["igual", "distinto", "agregar", "error"])
        self.assertEqual((scipio["renglones"][1]["actual"], scipio["renglones"][1]["precio"]), (241.78, 250))
        self.assertTrue(scipio["existe"])
        self.assertIsNone(scipio["asignar_de"])
        self.assertFalse(aerarg["existe"])
        self.assertEqual(aerarg["asignar_de"], "METCO")
        self.assertEqual([r["estado"] for r in aerarg["renglones"]], ["agregar", "no_cargar"])
        self.assertEqual(aerarg["renglones"][0]["precio"], 12.5)
        self.assertEqual(plan["resumen"]["agregar"], 2)
        self.assertEqual(plan["resumen"]["con_observaciones"], 1)

    def test_carga_completa(self):
        plan = self.imp.analizar(excel(LIBRO))
        self.imp.aplicar(plan["id"], "Estela", actualizar_distintos=True, saltear_observaciones=False)
        fin = self.esperar()
        self.assertEqual(fin["errores"], [])
        self.assertEqual(fin["hechos"], fin["total"])
        # SCIPIO: el distinto se corrigio y el nuevo entro como especial del cliente
        self.assertEqual(self.tango.renglones[1352]["GVA13"][0]["PRECIO"], 250)
        nuevo = next(r for r in self.tango.renglones.values() if r["COD_ARTICU"] == "1000125")
        self.assertEqual((nuevo["ID_GVA10"], nuevo["PRECIO"], nuevo["GVA13"][0]["PRECIO"], nuevo["GVA13"][0]["ID_GVA14"]), (6, 0, 99.5, 660))
        # AERARG: lista 24 en dolares, asignada al cliente, con su precio especial
        l24 = next(l for l in self.tango.listas.values() if l["NRO_DE_LIS"] == 24)
        self.assertEqual((l24["NOMBRE_LIS"], l24["MON_CTE"]), ("AERARG", False))
        self.assertEqual(self.tango.fichas[309]["ID_GVA10"], l24["ID_GVA10"])
        r = next(r for r in self.tango.renglones.values() if r["ID_GVA10"] == l24["ID_GVA10"])
        self.assertEqual((r["COD_ARTICU"], r["GVA13"][0]["PRECIO"], r["GVA13"][0]["ID_GVA14"]), ("1PAR00001", 12.5, 309))
        # el plan no se puede aplicar dos veces, y repetir la importacion no duplica
        with self.assertRaises(PedidoInvalido):
            self.imp.aplicar(plan["id"], "Estela", True, False)
        otra = self.imp.analizar(excel(LIBRO))
        self.assertEqual(otra["resumen"]["agregar"], 0)
        self.assertEqual(otra["resumen"]["distinto"], 0)

    def test_saltear_observaciones_y_sin_actualizar(self):
        plan = self.imp.analizar(excel(LIBRO))
        self.imp.aplicar(plan["id"], "Estela", actualizar_distintos=False, saltear_observaciones=True)
        self.esperar()
        self.assertEqual(self.tango.renglones[1352]["GVA13"][0]["PRECIO"], 241.78)    # no se toco

    def test_errores_de_lista(self):
        libro = dict(LIBRO)
        libro["Listas"] = [["Nro lista", "Descripción", "Cliente"], [10, "SCIPI", "SCIPIO"], [24, "SCIPIO", "AERARG"]]
        plan = self.imp.analizar(excel(libro))
        self.assertEqual(plan["listas"][0]["error"], "")                       # el nombre distinto solo se avisa
        self.assertEqual(plan["listas"][0]["nota"], "En el Excel figura como SCIPI.")
        self.assertIn("Ya hay otra lista llamada SCIPIO", plan["listas"][1]["error"])
        # precios de AERARG con el numero de la lista de SCIPIO: error
        libro["Listas"] = [["Nro lista", "Descripción", "Cliente"], [10, "SCIPIO", "AERARG"]]
        libro["Precios por cliente"] = [CABECERA, [10, "AERARG", "", "1000125", "", "KG", 5, "SÍ", None, None]]
        plan = self.imp.analizar(excel(libro))
        self.assertIn("la usa SCIPIO y no AERARG", plan["listas"][0]["error"])


if __name__ == "__main__":
    unittest.main()
