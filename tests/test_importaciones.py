"""Importaciones: en camino y precio de compra a partir de las tablas de carpetas."""

import json
import subprocess
import unittest
from unittest import mock

from herramienta_tango import base_tango, importaciones

DATOS = {
    "columnas": ["ID_CARPETA", "FECHA_APER", "ESTADO", "COD_PROVEE", "MON_CTE", "COTIZACION"],
    "carpetas": [
        {"ID_CARPETA": "0000100000979", "FECHA_APER": "2026-09-22", "ESTADO": "C", "COD_PROVEE": "OERLI", "NOMBRE_PROVEEDOR": "OERLIKON METCO US",
         "MON_CTE": False, "COTIZACION": 1593.05},
        {"ID_CARPETA": "0000100000981", "FECHA_APER": "2026-11-02", "ESTADO": "A", "COD_PROVEE": "OERLI", "NOMBRE_PROVEEDOR": "OERLIKON METCO US",
         "MON_CTE": False, "COTIZACION": 1600},
    ],
    "renglones": [
        # carpeta cerrada: no cuenta como en camino aunque le falte algo
        {"ID_CARPETA": "0000100000979", "COD_ARTICU": "1020646", "CANT_PEDID": 1100, "CANT_NACIO": 1094, "CANT_FACTU": 1100, "PREC_ORIG": 17.84, "CAN_EQUIVA": 1},
        {"ID_CARPETA": "0000100000981", "COD_ARTICU": "1020646", "CANT_PEDID": 500, "CANT_NACIO": 0, "CANT_FACTU": 0, "PREC_ORIG": 18.5, "CAN_EQUIVA": 1},
        # comprado en libras, stock en kilos: equivalencia 0,45359237 kg por lb
        {"ID_CARPETA": "0000100000981", "COD_ARTICU": "1000125", "CANT_PEDID": 110, "CANT_NACIO": 55, "CANT_FACTU": 110, "PREC_ORIG": 34.28, "CAN_EQUIVA": 0.45359237},
        # renglon de una carpeta sin cabecera: igual se muestra
        {"ID_CARPETA": "0000100000990", "COD_ARTICU": "0039812", "CANT_PEDID": 4, "CANT_NACIO": 0, "PREC_ORIG": 0, "CAN_EQUIVA": None},
    ],
    "despachos": [{"ID_CARPETA": "0000100000979", "N_DESPACHO": "26073IC04115196E", "N_PARTIDA": "97899", "FECHA": "2026-10-16"}],
}


class TestImportaciones(unittest.TestCase):
    def test_en_camino_y_precio(self):
        r = importaciones.armar(DATOS)
        a = r["articulos"]["1020646"]
        self.assertEqual(a["en_camino"], 500)                       # solo la carpeta abierta
        self.assertEqual([c["corto"] for c in a["carpetas_en_camino"]], ["981"])
        self.assertEqual((a["ultima_compra"]["corto"], a["ultima_compra"]["precio"], a["ultima_compra"]["moneda"]), ("981", 18.5, "US$"))
        self.assertEqual([c["corto"] for c in a["compras"]], ["981", "979"])  # la mas nueva primero

        b = r["articulos"]["1000125"]
        self.assertAlmostEqual(b["en_camino"], 55 * 0.45359237, places=3)     # 55 lb que faltan, en kg
        self.assertAlmostEqual(b["ultima_compra"]["precio"], 34.28 / 0.45359237, places=2)  # precio por kg

        c = r["articulos"]["0039812"]
        self.assertEqual((c["en_camino"], c["ultima_compra"]), (4, None))     # sin precio cargado

        car = {x["corto"]: x for x in r["carpetas"]}
        self.assertEqual((car["979"]["numero"], car["979"]["cerrada"], car["979"]["proveedor"]), ("00001-00000979", True, "OERLIKON METCO US"))
        self.assertEqual(car["979"]["despachos"][0]["despacho"], "26073IC04115196E")
        self.assertFalse(car["981"]["cerrada"])
        self.assertEqual(r["columnas_carpeta"][0], "ID_CARPETA")

    def test_una_sola_fila_llega_como_objeto(self):
        r = importaciones.armar({"carpetas": DATOS["carpetas"][1], "renglones": DATOS["renglones"][1], "despachos": None})
        self.assertEqual(r["articulos"]["1020646"]["en_camino"], 500)

    def test_lee_de_la_base(self):
        base_tango._cache.clear()
        with mock.patch.object(base_tango.sys, "platform", "win32"), \
             mock.patch.object(base_tango, "es_servidor", return_value=True), \
             mock.patch.object(base_tango.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, json.dumps(DATOS), "")) as run:
            r = base_tango.importaciones_datos()
            base_tango.importaciones_datos()                       # segunda vez: de la cache
        self.assertEqual(run.call_count, 1)
        script = run.call_args[0][0][-1]
        self.assertIn("FROM CPA66", script)
        for palabra in ("INSERT", "UPDATE ", "DELETE", "DROP"):
            self.assertNotIn(palabra, script.upper())
        self.assertIn("1020646", r["articulos"])


if __name__ == "__main__":
    unittest.main()
