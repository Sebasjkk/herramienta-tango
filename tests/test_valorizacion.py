"""Valorizacion del stock de Central en dolares, con el criterio de la Simulacion de costos de Tango."""

import io
import json
import subprocess
import unittest
import zipfile
from unittest import mock

from herramienta_tango import base_tango, valorizacion

C979, C862 = "0000100000979", "0000100000862"

DATOS = {
    "partidas": [
        {"ID_STA08": 1, "N_PARTIDA": "97899", "N_DESPACHO": "26073IC04115196E", "ID_CARPETA": C979, "FECHA": "2026-10-16"},
        {"ID_STA08": 2, "N_PARTIDA": "99999", "N_DESPACHO": "", "ID_CARPETA": "", "FECHA": "2019-05-01"},
        {"ID_STA08": 3, "N_PARTIDA": "50001", "N_DESPACHO": "16001IC04000001A", "ID_CARPETA": C862, "FECHA": "2016-03-01"},
        {"ID_STA08": 4, "N_PARTIDA": "AJV1", "N_DESPACHO": None, "ID_CARPETA": None, "FECHA": "2026-11-12"},
    ],
    "renglones": [
        {"ID_CARPETA": C979, "COD_ARTICU": "1000143", "CANT_FACTU": 1000, "CAN_EQUIVA": 1},
        {"ID_CARPETA": C862, "COD_ARTICU": "1000143", "CANT_FACTU": 10, "CAN_EQUIVA": 1},
        {"ID_CARPETA": C862, "COD_ARTICU": "EQUIPO", "CANT_FACTU": 1, "CAN_EQUIVA": None},
        # comprado en libras (110 lb), stock en kilos
        {"ID_CARPETA": C979, "COD_ARTICU": "LIBRA", "CANT_FACTU": 110, "CAN_EQUIVA": 0.45359237},
    ],
    "gastos": [
        {"ID_CARPETA": C979, "COD_ARTICU": "1000143", "COD_GASTO": "PRE", "IMPORTE": 9090, "MON_CTE": False, "COTIZACION": 1617.9},
        {"ID_CARPETA": C862, "COD_ARTICU": "1000143", "COD_GASTO": "PRE", "IMPORTE": 80, "MON_CTE": False, "COTIZACION": 15},
        # factura en pesos: se pasa a dolares con su cotizacion
        {"ID_CARPETA": C862, "COD_ARTICU": "EQUIPO", "COD_GASTO": "PRE", "IMPORTE": 3000000, "MON_CTE": True, "COTIZACION": 1000},
        {"ID_CARPETA": C979, "COD_ARTICU": "LIBRA", "COD_GASTO": "PRE", "IMPORTE": 3770.8, "MON_CTE": False, "COTIZACION": 1617.9},
        # gasto de despacho en pesos (USD 10), Tango le asigna la mitad a la partida 97899 de 1000143
        {"ID_CARPETA": C979, "COD_ARTICU": "", "COD_GASTO": "DES", "IMPORTE": 10000, "MON_CTE": True, "COTIZACION": 1000, "ID_DISTRIB": 7},
    ],
    "distribucion": [{"ID_DISTRIB": 7, "N_PARTIDA": "97899", "COD_ARTICU": "1000143", "IMPORTE": 5000}],
    "saldos": [
        {"COD_ARTICU": "1000143", "N_PARTIDA": "97899", "COD_DEPOSI": " 1", "CANTIDAD": 600, "CANT_DESPA": 1000, "COSTO_EX": 0, "ID_STA08": 1},
        {"COD_ARTICU": "1000143", "N_PARTIDA": "97899", "COD_DEPOSI": " 3", "CANTIDAD": 400, "CANT_DESPA": 0, "COSTO_EX": 0, "ID_STA08": 1},
        {"COD_ARTICU": "1000143", "N_PARTIDA": "99999", "COD_DEPOSI": " 1", "CANTIDAD": 3, "CANT_DESPA": 0, "COSTO_EX": 0, "ID_STA08": 2},
        {"COD_ARTICU": "EQUIPO", "N_PARTIDA": "50001", "COD_DEPOSI": " 1", "CANTIDAD": 2, "CANT_DESPA": 2, "COSTO_EX": 0, "ID_STA08": 3},
        {"COD_ARTICU": "SINREF", "N_PARTIDA": "99999", "COD_DEPOSI": " 1", "CANTIDAD": 5, "CANT_DESPA": 0, "COSTO_EX": None, "ID_STA08": 2},
        {"COD_ARTICU": "TANGOC", "N_PARTIDA": "AJV1", "COD_DEPOSI": " 1", "CANTIDAD": 4, "CANT_DESPA": 0, "COSTO_EX": 12.5, "ID_STA08": 4},
        {"COD_ARTICU": "NEG", "N_PARTIDA": "99999", "COD_DEPOSI": " 1", "CANTIDAD": -2, "CANT_DESPA": 0, "COSTO_EX": 0, "ID_STA08": 2},
        {"COD_ARTICU": "INSUMOS", "N_PARTIDA": "99999", "COD_DEPOSI": " 1", "CANTIDAD": 100, "CANT_DESPA": 0, "COSTO_EX": 0, "ID_STA08": 2},
        {"COD_ARTICU": "LIBRA", "N_PARTIDA": "97899", "COD_DEPOSI": " 1", "CANTIDAD": 49.8951607, "CANT_DESPA": 49.8951607, "COSTO_EX": 0, "ID_STA08": 1},
    ],
    "articulos": [{"COD_ARTICU": "1000143", "DESCRIPCIO": "METCO 1000143"}, {"COD_ARTICU": "EQUIPO", "DESCRIPCIO": "FLEXI ARC 200"}],
    "sin_partidas": [
        {"COD_ARTICU": "VIEJO", "COD_DEPOSI": " 1", "CANT_STOCK": 7},
        {"COD_ARTICU": "VIEJO2", "COD_DEPOSI": " 1", "CANT_STOCK": -3},
        {"COD_ARTICU": "1000143", "COD_DEPOSI": " 1", "CANT_STOCK": 603},      # lleva partidas: ya esta en el detalle
        {"COD_ARTICU": "OTRO", "COD_DEPOSI": " 2", "CANT_STOCK": 9},           # otro deposito
    ],
}


class Calculo(unittest.TestCase):
    def setUp(self):
        self.r = valorizacion.calcular(DATOS)
        self.por = {(f["codigo"], f["partida"]): f for f in self.r["filas"]}

    def test_costo_de_la_carpeta_con_gastos(self):
        f = self.por[("1000143", "97899")]
        self.assertEqual(f["origen"], "carpeta")
        self.assertAlmostEqual(f["costo"], 9.095)            # 9.090 / 1000 + USD 5 / 1000 despachados
        self.assertAlmostEqual(f["valor"], 5457)
        self.assertEqual(f["carpeta"], "979")
        self.assertEqual(f["anio"], "2026")

    def test_factura_en_pesos_y_para_verificar(self):
        f = self.por[("EQUIPO", "50001")]
        self.assertAlmostEqual(f["costo"], 3000)
        self.assertTrue(f["verificar"])
        self.assertFalse(self.por[("1000143", "97899")]["verificar"])

    def test_unidad_de_compra_distinta(self):
        f = self.por[("LIBRA", "97899")]
        self.assertAlmostEqual(f["costo"], 3770.8 / (110 * 0.45359237), places=3)
        self.assertAlmostEqual(f["valor"], 3770.8, places=1)

    def test_sin_carpeta(self):
        self.assertEqual(self.por[("TANGOC", "AJV1")]["origen"], "tango")
        self.assertAlmostEqual(self.por[("TANGOC", "AJV1")]["valor"], 50)
        f = self.por[("1000143", "99999")]                    # la importacion mas nueva: 979, no 862
        self.assertEqual((f["origen"], f["costo"], f["referencia"]), ("ultima", 9.09, "979"))
        f = self.por[("SINREF", "99999")]
        self.assertEqual(f["origen"], "sin")
        self.assertIsNone(f["valor"])

    def test_fuera_del_total(self):
        codigos = {f["codigo"] for f in self.r["filas"]}
        self.assertNotIn("INSUMOS", codigos)
        self.assertNotIn("NEG", codigos)
        self.assertEqual([f["codigo"] for f in self.r["negativos"]], ["NEG"])
        self.assertEqual(len([f for f in self.r["filas"] if f["codigo"] == "1000143"]), 2)    # el deposito 3 no
        self.assertEqual([f["codigo"] for f in self.r["sin_partidas"]], ["VIEJO", "VIEJO2"])

    def test_resumen(self):
        res = self.r["resumen"]
        self.assertAlmostEqual(res["total"], 5457 + 27.27 + 6000 + 50 + 3770.8, places=1)
        self.assertEqual(res["renglones"], 6)
        self.assertEqual(res["por_origen"]["sin"], {"renglones": 1, "valor": 0})
        self.assertEqual(res["por_origen"]["carpeta"]["renglones"], 3)
        self.assertEqual([a["anio"] for a in res["por_anio"]], ["2016", "2019", "2026"])
        self.assertEqual(res["verificar"]["renglones"], 1)
        self.assertEqual(res["negativos"]["renglones"], 1)
        self.assertEqual(self.r["filas"][0]["codigo"], "EQUIPO")      # del mas caro al mas barato

    def test_una_sola_fila_llega_como_objeto(self):
        d = dict(DATOS, saldos=DATOS["saldos"][0], sin_partidas=None)
        self.assertEqual(len(valorizacion.calcular(d)["filas"]), 1)

    def test_excel(self):
        contenido = valorizacion.excel(self.r, "2026-11-23 10:00")
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            libro = z.read("xl/workbook.xml").decode()
        for hoja in ("Resumen", "Detalle", "Para verificar", "Sin costo", "Saldos negativos", "Sin partidas"):
            self.assertIn(hoja, libro)


class Base(unittest.TestCase):
    def test_lee_de_la_base_solo_con_select(self):
        base_tango._cache.clear()
        with mock.patch.object(base_tango.sys, "platform", "win32"), \
             mock.patch.object(base_tango, "es_servidor", return_value=True), \
             mock.patch.object(base_tango.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, json.dumps(DATOS), "")) as run:
            r = base_tango.valorizacion_datos()
            base_tango.valorizacion_datos()                     # segunda vez: de la cache
            base_tango.responder_remoto("valorizacion", {})
        self.assertEqual(run.call_count, 1)
        script = run.call_args[0][0][-1]
        self.assertIn("FROM STA10", script)
        for palabra in ("INSERT", "UPDATE ", "DELETE", "DROP", "EXEC"):
            self.assertNotIn(palabra, script.upper())
        self.assertIn("calculado", r)
        self.assertGreater(r["resumen"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
