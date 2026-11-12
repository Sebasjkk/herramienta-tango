"""
Pruebas de la capa Tango y del servidor, sin conectarse a un Tango real.

Los registros de ejemplo tienen la misma forma que las respuestas reales de la
API, con datos inventados.
Se ejecutan con:  python -m unittest discover -s tests
"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date

import tempfile
from pathlib import Path
from unittest import mock

from herramienta_tango import config, credenciales
from herramienta_tango.contexto import Contexto
from herramienta_tango.tango import TokenInvalido, procesos
from herramienta_tango.tango.modelos import Articulo, Pedido, SaldoPartida
from herramienta_tango.tango.servicio import ServicioTango
from herramienta_tango.web.servidor import crear_servidor

CFG = config.Config(servidor="http://tango-prueba:17000", company="3", timeout=5, puerto=0,
                    vigencia_saldos=60, repo_actualizaciones="", actualizacion_automatica=False,
                    actualizacion_cada_minutos=15)
TOKEN_OK = "11111111-2222-3333-4444-555555555555"

SALDO = {"ID_STA08": 7, "ID_STA11": 2091, "ID_STA22": 1, "PARTIDA": " 709 ",
         "NUMERO_DE_DESPACHO": "16073IC04087780K", "FECHA_DE_VENCIMIENTO": "2016-11-15T00:00:00",
         "COD_COMPROBANTE": "REM", "COD_ARTICULO": "01029071", "DESCRIPCION": "POLVO PRUEBA ",
         "DESCRIPCION_DEPOSITO": "CENTRAL", "UM_CONTROL_STOCK": "KG", "SALDO_CONTROL_STOCK": -6.8100001,
         "SERIE": "Detalle"}
ARTICULO = {"COD_STA11": "1PAR00011", "DESCRIPCIO": "REPUESTO PRUEBA", "DESC_ADIC": "", "SINONIMO": "",
            "COD_BARRA": "", "ID_STA11": 4, "USA_PARTID": False, "STOCK": True, "PERFIL": "A",
            "MEDIDA_STOCK_SIGLA": "UNI", "COD_NCM": "8424.90.90", "STOCK_MINI": 0.0, "STOCK_MAXI": 0.0,
            "PTO_PEDIDO": 2.0}
PEDIDO = {"ID_GVA21": 1, "NRO_PEDIDO": " 00000-00000017", "CODIGO_CLIENTE": "CLI01",
          "RAZON_SOCIAL_CLIENTE": "CLIENTE PRUEBA S.A.", "FECHA_PEDI": "2006-09-28T00:00:00", "ESTADO": 2,
          "FECHA_ENTR": None, "NRO_OC_COMP": "OC-123", "FECHA_O_COMP": None, "NOMBRE_SUC": "CENTRAL",
          "NOMBRE_LIS": "METCO", "TOTAL_PEDI": 10.5, "LEYENDA_1": "", "LEYENDA_2": "Urgente"}


class ClienteFalso:
    """Reemplaza al cliente HTTP: cuenta cuantas veces se le pidio cada proceso."""

    def __init__(self):
        self.llamadas = []

    def consulta_live(self, proceso, desde=None, hasta=None):
        self.llamadas.append((proceso, desde, hasta))
        return [SALDO]

    def listar(self, proceso, vista=""):
        self.llamadas.append((proceso,))
        return {procesos.ARTICULOS: [ARTICULO], procesos.PEDIDOS: [PEDIDO]}.get(proceso, [])


class TestModelos(unittest.TestCase):
    def test_saldo_partida(self):
        s = SaldoPartida.desde_tango(SALDO)
        self.assertEqual(s.partida, "709")
        self.assertEqual(s.descripcion, "POLVO PRUEBA")
        self.assertEqual(s.vencimiento, "2016-11-15")
        self.assertAlmostEqual(s.saldo, -6.81)

    def test_articulo(self):
        a = Articulo.desde_tango(ARTICULO)
        self.assertEqual(a.codigo, "1PAR00011")
        self.assertFalse(a.usa_partidas)
        self.assertEqual(a.ncm, "8424.90.90")
        self.assertEqual(a.punto_pedido, 2.0)

    def test_pedido(self):
        p = Pedido.desde_tango(PEDIDO)
        self.assertEqual(p.numero, "00000-00000017")
        self.assertEqual(p.orden_compra_cliente, "OC-123")
        self.assertEqual(p.leyendas, ("Urgente",))

    def test_campos_faltantes_no_rompen(self):
        s = SaldoPartida.desde_tango({})
        self.assertEqual((s.codigo_articulo, s.saldo, s.vencimiento), ("", 0.0, None))


class TestServicio(unittest.TestCase):
    def test_cache(self):
        cliente = ClienteFalso()
        servicio = ServicioTango(cliente)
        servicio.saldos_por_partida()
        servicio.saldos_por_partida()
        self.assertEqual(len(cliente.llamadas), 1, "la segunda consulta tiene que salir de la cache")
        servicio.saldos_por_partida(forzar=True)
        self.assertEqual(len(cliente.llamadas), 2)

    def test_ventas_por_rango(self):
        cliente = ClienteFalso()
        servicio = ServicioTango(cliente)
        servicio.ventas(date(2026, 10, 1), date(2026, 10, 31))
        self.assertEqual(cliente.llamadas[-1], (procesos.LIVE_VENTAS_DETALLE, date(2026, 10, 1), date(2026, 10, 31)))


class ClienteConToken:
    """Cliente falso para probar la configuracion: solo acepta TOKEN_OK."""

    def __init__(self, servidor, company, token, timeout):
        self.token = token

    def listar(self, proceso, vista=""):
        if self.token != TOKEN_OK:
            raise TokenInvalido("401")
        return []

    def consulta_live(self, proceso, desde=None, hasta=None):
        return [SALDO]


class TestServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        carpeta = Path(cls.tmp.name)
        cls.parches = [mock.patch.object(config, "RUTA_CONFIG", carpeta / "config.ini"),
                       mock.patch.object(config, "RUTA_TOKEN", carpeta / "token.dat"),
                       mock.patch.dict("os.environ", {"HERRAMIENTA_TANGO_TOKEN": ""})]
        for p in cls.parches:
            p.start()
        cls.contexto = Contexto(CFG, fabrica_cliente=ClienteConToken)
        cls.contexto._servicio = ServicioTango(ClienteFalso())
        cls.servidor = crear_servidor(cls.contexto, 0)
        cls.base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        threading.Thread(target=cls.servidor.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        for p in cls.parches:
            p.stop()
        cls.tmp.cleanup()

    def _get(self, ruta):
        try:
            with urllib.request.urlopen(self.base + ruta) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def _post(self, ruta, datos, encabezado=True):
        pedido = urllib.request.Request(self.base + ruta, data=json.dumps(datos).encode(), method="POST",
                                        headers={"Content-Type": "application/json",
                                                 **({"X-Herramienta-Tango": "1"} if encabezado else {})})
        try:
            with urllib.request.urlopen(pedido) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_panel_y_estado_del_sistema(self):
        estado, cuerpo = self._get("/panel")
        self.assertEqual(estado, 200)
        self.assertIn(b"Herramienta", cuerpo)
        estado, cuerpo = self._get("/api/sistema")
        datos = json.loads(cuerpo)
        self.assertEqual(estado, 200)
        self.assertTrue(datos["configurado"])

    def test_post_sin_encabezado_se_rechaza(self):
        estado, _ = self._post("/api/sistema/probar", {}, encabezado=False)
        self.assertEqual(estado, 403)

    def test_configurar_con_token_malo(self):
        estado, datos = self._post("/api/sistema/configurar",
                                   {"servidor": "tango-prueba:17000", "token": "99999999-2222-3333-4444-555555555555"})
        self.assertEqual(estado, 400)
        self.assertIn("rechazó", datos["mensaje"])
        # No se guarda un token rechazado (si hay uno guardado, es el bueno de otra prueba)
        if config.RUTA_TOKEN.exists():
            self.assertEqual(credenciales.leer_token(), TOKEN_OK)  # en Windows esta cifrado

    def test_configurar_sin_puerto(self):
        estado, datos = self._post("/api/sistema/configurar", {"servidor": "tango-prueba", "token": TOKEN_OK})
        self.assertEqual(estado, 400)
        self.assertIn("puerto", datos["mensaje"])

    def test_configurar_bien_guarda(self):
        estado, datos = self._post("/api/sistema/configurar",
                                   {"servidor": "http://tango-prueba:17000/company/3/menu", "token": TOKEN_OK})
        self.assertEqual(estado, 200, datos)
        self.assertEqual(datos["sistema"]["servidor"], "http://tango-prueba:17000")
        self.assertEqual(credenciales.leer_token(), TOKEN_OK)
        self.assertIn("tango-prueba:17000", config.RUTA_CONFIG.read_text(encoding="utf-8"))

    def test_partidas(self):
        estado, cuerpo = self._get("/api/stock/partidas")
        datos = json.loads(cuerpo)
        self.assertEqual(estado, 200)
        self.assertTrue(datos["ok"])
        self.assertEqual(datos["datos"][0]["partida"], "709")

    def test_pagina(self):
        estado, cuerpo = self._get("/")
        self.assertEqual(estado, 200)
        self.assertIn(b'id="modulos"', cuerpo)          # menu de inicio
        self.assertIn(b"/stock", cuerpo)
        estado, cuerpo = self._get("/stock")
        self.assertEqual(estado, 200)
        self.assertIn(b"Stock por partida", cuerpo)

    def test_no_sale_de_la_carpeta_estatica(self):
        estado, _ = self._get("/../../config.py")
        self.assertEqual(estado, 404)

    def test_fecha_invalida(self):
        estado, cuerpo = self._get("/api/ventas?desde=ayer")
        self.assertEqual(estado, 400)
        self.assertFalse(json.loads(cuerpo)["ok"])

    def test_solo_lectura(self):
        estado, _ = self._post("/api/stock/partidas", {})
        self.assertEqual(estado, 405)

    def test_consulta_inexistente(self):
        estado, _ = self._get("/api/no-existe")
        self.assertEqual(estado, 404)


if __name__ == "__main__":
    unittest.main()


class TestConfig(unittest.TestCase):
    def test_normalizar_servidor(self):
        n = config.normalizar_servidor
        self.assertEqual(n("pc-tango:17000"), "http://pc-tango:17000")
        self.assertEqual(n("http://pc-tango:17000/login-redirect/%7BABC%7D/-1"), "http://pc-tango:17000")
        self.assertTrue(config.servidor_valido(n("pc-tango:17000")))
        self.assertFalse(config.servidor_valido(n("pc-tango")))

    def test_empresa_por_defecto(self):
        self.assertEqual(config.DEFECTO["tango"]["company"], "3")


class TestSinConfigurar(unittest.TestCase):
    def test_tango_responde_503(self):
        contexto = Contexto(CFG)
        servidor = crear_servidor(contexto, 0)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{servidor.server_address[1]}/api/stock/partidas")
            self.fail("tenia que fallar")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 503)
        finally:
            servidor.shutdown()
            servidor.server_close()
