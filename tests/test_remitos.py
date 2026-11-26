"""Pruebas de la pantalla de Remitos (sin Tango ni base reales)."""
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from herramienta_tango import base_tango, remitos


def remito(i, numero, pedido=""):
    return SimpleNamespace(id=i, numero=numero, numero_corto=numero, fecha="2026-11-01", id_cliente=1,
                           codigo_cliente="C1", cliente="CLIENTE", estado="Normal", pedido=pedido)


class Servicio:
    def remitos(self, forzar=False):
        return [remito(1, "R0000800000110"), remito(2, "R0000800000111", pedido="0000000000037"),
                remito(3, "R0000800000112")], 0

    def pedidos(self, forzar=False):
        return [SimpleNamespace(id=24, numero="0000000000037", orden_compra_cliente="OC-555", estado=2)], 0


class TestVista(unittest.TestCase):
    def test_pedidos_desde_la_base(self):
        base = {"relacion": True, "remitos": {"R0000800000110": [{"id": 24, "numero": "0000000000037"}],
                                              "R0000800000111": [{"id": 24, "numero": "0000000000037"}]},
                "facturas": {"R0000800000110": [{"tipo": "Factura", "numero": "A 0003-00013009"}]}}
        with mock.patch.object(base_tango, "remitos_con_pedido", return_value=base):
            d, _ = remitos.vista(Servicio())
        r = {x["id"]: x for x in d["remitos"]}
        self.assertEqual(d["origen"], "base")
        self.assertEqual(r[1]["pedidos"][0]["orden_compra"], "OC-555")     # entrega parcial anterior: tambien con pedido
        self.assertEqual(r[2]["pedidos"][0]["numero"], "0000000000037")
        self.assertEqual(r[3]["pedidos"], [])
        self.assertEqual(r[1]["facturas"][0]["numero"], "A 0003-00013009")
        self.assertEqual(r[3]["facturas"], [])                              # sin facturar

    def test_sin_base_usa_el_ultimo_remito_y_avisa(self):
        with mock.patch.object(base_tango, "remitos_con_pedido", side_effect=base_tango.BaseNoDisponible("sin base.")):
            d, _ = remitos.vista(Servicio())
        r = {x["id"]: x for x in d["remitos"]}
        self.assertEqual(d["origen"], "ultimo_remito")
        self.assertIn("sin base", d["aviso"])
        self.assertEqual(r[1]["pedidos"], [])
        self.assertEqual(r[2]["pedidos"][0]["orden_compra"], "OC-555")


class TestBase(unittest.TestCase):
    def setUp(self):
        base_tango._cache.clear()
        for p in (mock.patch.object(base_tango.sys, "platform", "win32"),
                  mock.patch.object(base_tango, "es_servidor", return_value=True)):
            p.start(); self.addCleanup(p.stop)

    def correr(self, js):
        return mock.patch.object(base_tango.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, js, ""))

    def test_remitos_con_pedido(self):
        js = ('{"relacion":true,"filas":[{"N_COMP":"R0000800000110","ID_PEDIDO":24,"NRO_PEDIDO":"0000000000037"},'
              '{"N_COMP":"R0000800000110","ID_PEDIDO":25,"NRO_PEDIDO":"0000000000038"}],'
              '"facturas":{"N_COMP":"R0000800000110","T_COMP":"FAC","N_FAC":"A0000300013009"}}')
        with self.correr(js) as run:
            d = base_tango.remitos_con_pedido()
        self.assertIn("REFERENCIA_REMITO", run.call_args[0][0][-1])
        self.assertIn("FROM GVA54 f", run.call_args[0][0][-1])
        self.assertEqual(len(d["remitos"]["R0000800000110"]), 2)
        self.assertEqual(d["facturas"]["R0000800000110"], [{"tipo": "Factura", "numero": "A 0003-00013009"}])

    def test_renglones_con_partidas_y_una_sola_fila(self):
        js = ('{"renglones":{"COD_ARTICU":"PA0007","DESCRIPCION":"POLVO","CANTIDAD":250,"TIPO_MOV":"S"},'
              '"tabla_partidas":"STA09","partidas":[{"COD_ARTICU":"PA0007","N_PARTIDA":"715","CANTIDAD":211.36},'
              '{"COD_ARTICU":"PA0007","N_PARTIDA":"716","CANTIDAD":38.64}]}')
        with self.correr(js) as run:
            d = base_tango.renglones_remito(40)
        self.assertIn("c.ID_STA14 = 40", run.call_args[0][0][-1])
        self.assertEqual(d["renglones"][0]["cantidad"], 250)
        self.assertEqual([p["partida"] for p in d["renglones"][0]["partidas"]], ["715", "716"])
        self.assertTrue(d["partidas_leidas"])

    def test_id_solo_entero(self):
        with self.assertRaises(ValueError):
            base_tango.renglones_remito("40; DROP TABLE STA14")


if __name__ == "__main__":
    unittest.main()


class TestDiagnostico(unittest.TestCase):
    def test_parte_del_ultimo_remito_de_un_pedido(self):
        with mock.patch.object(base_tango, "diag_pedido_remito", return_value={"coincidencias": []}) as d:
            r = remitos.diagnostico(Servicio())
        d.assert_called_once_with(24, 2)
        self.assertEqual(r["par"]["remito"], "R0000800000111")

    def test_script_solo_lectura(self):
        self.assertNotRegex(base_tango._DIAG_PEDIDO_REMITO.upper(), r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|EXEC)\b")


class TestDiagFactura(unittest.TestCase):
    def test_solo_lectura(self):
        self.assertNotRegex(base_tango._DIAG_FACTURA_REMITO.upper(), r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|EXEC)\b")

    def test_desde_otra_pc(self):
        with mock.patch.object(base_tango, "es_servidor", return_value=False), \
             mock.patch.object(base_tango, "_remoto", return_value={}) as r:
            base_tango.diag_factura_remito(32004)
        r.assert_called_once_with("diag_factura_remito", {"remito": 32004}, tiempo=260)
