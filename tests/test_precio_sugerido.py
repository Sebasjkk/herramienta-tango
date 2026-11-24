"""Pruebas del precio sugerido (sin Tango ni base reales)."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from herramienta_tango import base_tango, precio_sugerido as ps


def salida(stdout="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout, "")


class Servicio:
    def __init__(self, precios):
        self.editor = SimpleNamespace(precios_de_articulo=lambda cod: precios)

    def clientes(self):
        return [SimpleNamespace(codigo="SCIPIO", razon_social="SCIPIO SA", lista_precios="SCIPIO"),
                SimpleNamespace(codigo="METALI", razon_social="METALIZA", lista_precios="METCO")], 0

    def articulos(self):
        return [SimpleNamespace(codigo="0039812", descripcion="BELT", unidad="UN")], 0


PRECIOS = [
    {"id": 1, "lista": "SCIPIO", "moneda": "US$", "precio": 0, "especiales": [{"codigo_cliente": "SCIPIO", "precio": 241.78}]},
    {"id": 2, "lista": "METCO", "moneda": "US$", "precio": 300.0, "especiales": []},
]
VENTAS = {"filas": [
    {"fecha": "2026-10-01", "t_comp": "FAC", "codigo_cliente": "SCIPIO", "precio_usd": 240.0, "cantidad": 2},
    {"fecha": "2026-09-01", "t_comp": "FAC", "codigo_cliente": "METALI", "precio_usd": 290.0, "cantidad": 1},
], "aviso": None}


class TestArmar(unittest.TestCase):
    def test_precio_especial_y_ventas_separadas(self):
        with mock.patch.object(base_tango, "ventas_articulo", return_value=VENTAS):
            d = ps.armar(Servicio(PRECIOS), "0039812", "scipio")
        self.assertEqual(d["en_lista"]["precio"], 241.78)
        self.assertTrue(d["en_lista"]["especial"])
        self.assertEqual([v["codigo_cliente"] for v in d["ventas_cliente"]], ["SCIPIO"])
        self.assertEqual([v["codigo_cliente"] for v in d["ventas_otros"]], ["METALI"])
        self.assertEqual(d["articulo"]["descripcion"], "BELT")

    def test_precio_de_lista_y_sin_base(self):
        with mock.patch.object(base_tango, "ventas_articulo", side_effect=base_tango.BaseNoDisponible("sin base")):
            d = ps.armar(Servicio(PRECIOS), "0039812", "METALI")
        self.assertEqual(d["en_lista"]["precio"], 300.0)
        self.assertFalse(d["en_lista"]["especial"])
        self.assertEqual(d["ventas_error"], "sin base")

    def test_articulo_que_no_esta_en_la_lista(self):
        with mock.patch.object(base_tango, "ventas_articulo", return_value={"filas": []}):
            d = ps.armar(Servicio([PRECIOS[1]]), "0039812", "SCIPIO")
        self.assertTrue(d["en_lista"]["no_esta"])

    def test_sin_cliente(self):
        with mock.patch.object(base_tango, "ventas_articulo", return_value=VENTAS):
            d = ps.armar(Servicio(PRECIOS), "0039812", "")
        self.assertIsNone(d["cliente"])
        self.assertEqual(len(d["ventas_otros"]), 2)


class TestCosto(unittest.TestCase):
    def test_promedio_ponderado_del_stock(self):
        val = {"filas": [{"codigo": "A", "cantidad": 10, "costo": 10.0, "partida": "1"},
                         {"codigo": "A", "cantidad": 30, "costo": 20.0, "partida": "2"},
                         {"codigo": "B", "cantidad": 5, "costo": 99.0, "partida": "3"}]}
        with mock.patch.object(base_tango, "valorizacion_datos", return_value=val):
            c = ps.costo(None, "A")
        self.assertEqual(c["costo"], 17.5)
        self.assertEqual(c["origen"], "stock")

    def test_sin_stock_usa_la_ultima_importacion(self):
        imp = {"articulos": {"A": {"ultima_compra": {"precio": 12.5, "corto": "979", "fecha": "2026-08-10"}}}}
        with mock.patch.object(base_tango, "valorizacion_datos", return_value={"filas": []}), \
             mock.patch.object(base_tango, "importaciones_datos", return_value=imp):
            c = ps.costo(None, "A")
        self.assertEqual((c["costo"], c["origen"]), (12.5, "ultima_importacion"))


class TestVentasBase(unittest.TestCase):
    def setUp(self):
        base_tango._cache.clear()
        for p in (mock.patch.object(base_tango.sys, "platform", "win32"),
                  mock.patch.object(base_tango, "es_servidor", return_value=True)):
            p.start(); self.addCleanup(p.stop)

    def test_pasa_a_dolares(self):
        js = ('{"filas":[{"F_FECHA":"2026-10-01","F_CLIENTE":"SCIPIO","F_RAZON":"SCIPIO SA","F_MON_CTE":true,"F_COTIZ":1000,'
              '"T_COMP":"FAC","N_COMP":"A000100001234","CANTIDAD":2,"PRECIO_NET":241780,"PREC_ULC_E":150},'
              '{"F_FECHA":"2026-09-01","F_CLIENTE":"X","F_MON_CTE":false,"T_COMP":"FAC","N_COMP":"A000100001200","CANTIDAD":1,"PRECIO_NET":250}]}')
        with mock.patch.object(base_tango.subprocess, "run", return_value=salida(js)) as run:
            d = base_tango.ventas_articulo("0039812")
        self.assertIn("r.COD_ARTICU = '0039812'", run.call_args[0][0][-1])
        self.assertEqual(d["filas"][0]["precio_usd"], 241.78)
        self.assertEqual(d["filas"][0]["costo_al_vender_usd"], 150)
        self.assertEqual(d["filas"][1]["precio_usd"], 250)

    def test_codigo_invalido(self):
        with self.assertRaises(ValueError):
            base_tango.ventas_articulo("A'; DROP")


if __name__ == "__main__":
    unittest.main()
