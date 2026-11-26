"""Pruebas de los precios automaticos desde las cotizaciones (sin Tango ni base reales)."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from herramienta_tango import base_tango
from herramienta_tango.precios_auto import PreciosDesdeCotizaciones


class Editor:
    """Lista 66 del cliente SCIPIO: precio real como especial (lista en 0), como las de Sianco."""
    def __init__(self):
        self.listas = {66: {"ID_GVA10": 66, "NOMBRE_LIS": "SCIPIO", "MON_CTE": False},
                       1: {"ID_GVA10": 1, "NOMBRE_LIS": "METCO", "MON_CTE": False}}
        self.renglones = {500: {"ID_GVA17": 500, "ID_GVA10": 66, "COD_STA11": "A1", "PRECIO": 0,
                                "GVA13": [{"ID_GVA14": 660, "COD_CLIENT": "SCIPIO", "PRECIO": 13.80}]},
                          501: {"ID_GVA17": 501, "ID_GVA10": 66, "COD_STA11": "B2", "PRECIO": 0,
                                "GVA13": [{"ID_GVA14": 660, "COD_CLIENT": "SCIPIO", "PRECIO": 50.0}]}}
        self.cambios, self.agregados = [], []

    def _lista(self, i):
        return self.listas[i]

    def _todos_los_renglones(self, forzar=False):
        return list(self.renglones.values())

    def _leer_renglon(self, i):
        return self.renglones[i]

    def cambiar_precio(self, i, precio, quien, id_cliente=None):
        self.cambios.append((i, precio, quien, id_cliente))

    def agregar_articulo(self, lista, cod, precio, quien, id_cliente=None, codigo_cliente=""):
        self.agregados.append((lista, cod, precio, id_cliente, codigo_cliente))


class Servicio:
    def __init__(self, clientes):
        self.editor = Editor()
        self._clientes = clientes

    def clientes(self):
        return self._clientes, 0


def cliente(codigo, lista, i):
    return SimpleNamespace(codigo=codigo, lista_precios=lista, id=i)


def cot(i=10, lista=66, cli="SCIPIO", estado=2, en_pesos=False, renglones=None):
    return {"id": i, "numero": "0000100003231", "estado": estado, "id_lista": lista, "codigo_cliente": cli,
            "id_cliente": 660, "en_pesos": en_pesos, "renglones": renglones if renglones is not None else
            [{"codigo": "A1", "precio": 14.80}, {"codigo": "B2", "precio": 45.0}, {"codigo": "C3", "precio": 9.5}]}


class TestPreciosAuto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self.tmp.name) / "pa.json"

    def tearDown(self):
        self.tmp.cleanup()

    def armar(self, clientes=None):
        self.s = Servicio(clientes or [cliente("SCIPIO", "SCIPIO", 660), cliente("METALI", "METCO", 1)])
        return PreciosDesdeCotizaciones(lambda: self.s, self.ruta)

    def test_sube_agrega_y_no_baja(self):
        r = self.armar().procesar(cot())
        e = self.s.editor
        self.assertEqual(e.cambios, [(500, 14.80, "Automático: cotización BA3231", 660)])     # especial del cliente
        self.assertEqual(e.agregados, [(66, "C3", 9.5, 660, "SCIPIO")])
        self.assertEqual(r["omitidos"][0]["motivo"], "más barato")                           # B2 45 < 50: no se baja

    def test_lista_compartida_no_se_toca(self):
        pa = self.armar([cliente("SCIPIO", "SCIPIO", 660), cliente("OTRO", "SCIPIO", 7)])
        r = pa.procesar(cot())
        self.assertIn("no es propia", r["motivo"])
        self.assertEqual((self.s.editor.cambios, self.s.editor.agregados), ([], []))

    def test_lista_general_no_se_toca(self):
        r = self.armar().procesar(cot(lista=1))
        self.assertIn("no es propia", r["motivo"])
        self.assertEqual(self.s.editor.cambios, [])

    def test_otra_moneda_no_se_toca(self):
        r = self.armar().procesar(cot(en_pesos=True))
        self.assertIn("no se convierte", r["motivo"])
        self.assertEqual(self.s.editor.cambios, [])

    def test_no_emitida(self):
        r = self.armar().procesar(cot(estado=5))
        self.assertIn("No está emitida", r["motivo"])

    def test_primera_vez_arranca_desde_la_ultima(self):
        pa = self.armar()
        with mock.patch.object(base_tango, "cotizaciones_desde", return_value={"maximo": 1020, "cotizaciones": []}):
            self.assertEqual(pa.revisar(), [])
        self.assertEqual(pa.leer()["desde_id"], 1020)
        with mock.patch.object(base_tango, "cotizaciones_desde", return_value={"maximo": 1021, "cotizaciones": [cot(i=1021)]}) as q:
            hechos = pa.revisar()
        q.assert_called_once_with(1020)
        self.assertEqual(len(hechos), 1)
        self.assertEqual(pa.leer()["desde_id"], 1021)
        self.assertEqual(pa.leer()["historial"][-1]["cotizacion"], "BA3231")

    def test_script_solo_lectura(self):
        self.assertNotRegex(base_tango._COTIZACIONES_DESDE.upper(), r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|EXEC)\b")


if __name__ == "__main__":
    unittest.main()


class TestCotizacionesDesde(unittest.TestCase):
    def test_lee_cabeceras_y_renglones(self):
        import subprocess
        js = ('{"maximo":1021,"cabeceras":{"ID_GVA08":1021,"N_COTIZ":"0000100003231","ESTADO":2,"ID_GVA10":66,'
              '"COD_CLIENT":"SCIPIO ","ID_GVA14":660,"MON_CTE":false},'
              '"renglones":[{"ID_GVA08":1021,"COD_ARTICU":"A1","PRECIO":14.8,"N_RENGLON":1}]}')
        base_tango._cache.clear()
        with mock.patch.object(base_tango.sys, "platform", "win32"), \
             mock.patch.object(base_tango.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, js, "")) as run:
            d = base_tango.cotizaciones_desde(1020)
        self.assertIn("ID_GVA08 > 1020", run.call_args[0][0][-1])
        c = d["cotizaciones"][0]
        self.assertEqual((d["maximo"], c["codigo_cliente"], c["en_pesos"], c["renglones"][0]["precio"]), (1021, "SCIPIO", False, 14.8))
