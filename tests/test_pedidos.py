"""Pedidos: detalle y baja (con copia antes de borrar)."""

import tempfile
import unittest
from pathlib import Path

from herramienta_tango.pedidos import EditorPedidos
from herramienta_tango.precios import PedidoInvalido, RegistroCambios
from herramienta_tango.tango import TangoError

PEDIDO = {"ID_GVA21": 7, "NRO_PEDIDO": " 0000000000031", "FECHA_PEDIDO": "2007-02-10T00:00:00", "ESTADO": 3,
          "ID_GVA14": 660, "ID_GVA10": 6, "ID_MONEDA": 1, "NRO_ORDEN_COMPRA": "OC 55", "LEYENDA_1": "Martin", "LEYENDA_2": None,
          "COMPROMETE_STOCK": False, "RENGLON_DTO": [{"DESCRIPCION_ARTICULO": "POLVO", "CANTIDAD_PEDIDA": 2, "PRECIO": 10,
                                                      "CANTIDAD_PENDIENTE_A_FACTURAR": 0}],
          "NOTA_PEDIDO_DTO": [{"MENSAJE": "PEDIDO FACTURADO"}]}


class TangoFalso:
    def __init__(self, rechazar=""):
        self.datos = {19845: {7: dict(PEDIDO)}, 984: {6: {"NOMBRE_LIS": "REPOSICION", "NRO_DE_LIS": 6}},
                      2117: {660: {"COD_GVA14": "SCIPIO", "RAZON_SOCI": "AMG SCIPIONI"}}}
        self.rechazar = rechazar

    def obtener(self, proceso, id_):
        return self.datos.get(proceso, {}).get(id_)

    def borrar(self, proceso, id_):
        if self.rechazar:
            raise TangoError(f"Tango no pudo resolver el pedido: {self.rechazar}")
        self.datos[proceso].pop(id_, None)


class Servicio:
    def olvidar(self, clave):
        pass


class TestPedidos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.registro = RegistroCambios(Path(self.tmp.name) / "p.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_entrega_parcial(self):
        t = TangoFalso()
        t.datos[19845][8] = {**PEDIDO, "ID_GVA21": 8, "ESTADO": 2, "N_REMITO": " 0000800000110", "RENGLON_DTO": [
            {"COD_ARTICULO": "ZINC", "DESCRIPCION_ARTICULO": "ZINC", "CANTIDAD_PEDIDA": 100, "CANTIDAD_A_DESCARGAR": 40},
            {"COD_ARTICULO": "METCO", "DESCRIPCION_ARTICULO": "METCO", "CANTIDAD_PEDIDA": 20, "CANTIDAD_A_DESCARGAR": 20}]}
        t.datos[19845][9] = {**PEDIDO, "ID_GVA21": 9, "ESTADO": 2, "RENGLON_DTO": [
            {"DESCRIPCION_ARTICULO": "X", "CANTIDAD_PEDIDA": 5, "CANTIDAD_A_DESCARGAR": 0}]}
        e = EditorPedidos(t, Servicio(), self.registro)
        d = e.detalle(8)
        self.assertEqual([(r["codigo"], r["entregado"], r["falta"]) for r in d["renglones"]], [("ZINC", 60, 40), ("METCO", 0, 20)])
        self.assertEqual((d["entrega"]["estado_entrega"], d["entrega"]["entregado"], d["entrega"]["falta"], d["entrega"]["porcentaje"]),
                         ("parcial", 60, 60, 50))
        self.assertEqual(d["ultimo_remito"], "0000800000110")
        av = e.avance([8, 9, 999])          # el 999 no existe: queda afuera sin romper
        self.assertEqual({i: a["estado_entrega"] for i, a in av.items()}, {8: "parcial", 9: "entregado"})

    def test_detalle(self):
        d = EditorPedidos(TangoFalso(), Servicio(), self.registro).detalle(7)
        self.assertEqual((d["numero"], d["estado_texto"], d["lista_precios"], d["cliente"]["codigo"]),
                         ("0000000000031", "Cumplido", "REPOSICION", "SCIPIO"))
        self.assertEqual(d["leyendas"], ["Martin"])
        self.assertEqual(d["renglones"][0]["cantidad"], 2)
        self.assertEqual(d["notas"], ["PEDIDO FACTURADO"])

    def test_eliminar(self):
        t = TangoFalso()
        e = EditorPedidos(t, Servicio(), self.registro)
        with self.assertRaisesRegex(PedidoInvalido, "escribí su número: 31"):
            e.eliminar(7, "13", "Fran")
        e.eliminar(7, "0031", "Fran")
        self.assertNotIn(7, t.datos[19845])
        self.assertEqual(self.registro.ultimos()[0]["copia"]["NRO_PEDIDO"], " 0000000000031")

    def test_tango_rechaza_la_baja(self):
        t = TangoFalso(rechazar="Su licencia no incluye el uso del API de Transacciones Tango Ventas.")
        e = EditorPedidos(t, Servicio(), self.registro)
        with self.assertRaisesRegex(TangoError, "pedido 31: .*licencia"):
            e.eliminar(7, "31", "Fran")
        self.assertIn(7, t.datos[19845])
        self.assertEqual([c["accion"] for c in self.registro.ultimos()], ["error al eliminar pedido", "eliminar pedido"])


if __name__ == "__main__":
    unittest.main()


class TestOpciones(unittest.TestCase):
    def test_activar_eliminar_pedidos(self):
        from unittest import mock
        from herramienta_tango import config, opciones
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "CARPETA", Path(tmp)):
            self.assertFalse(opciones.leer()["pedidos_eliminar"])            # por defecto, inactivo
            self.assertTrue(opciones.cambiar("pedidos_eliminar", True)["pedidos_eliminar"])
            self.assertTrue(opciones.leer()["pedidos_eliminar"])
            with self.assertRaises(ValueError):
                opciones.cambiar("otra_cosa", True)
            with self.assertRaises(ValueError):
                opciones.cambiar("pedidos_eliminar", "si")
