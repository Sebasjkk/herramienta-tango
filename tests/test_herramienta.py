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
from herramienta_tango.tango.modelos import Articulo, Cotizacion, DatosEnvio, Pedido, PrecioVigente, Remito, SaldoPartida
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

PRECIO = {"COD_ARTICULO": "0039812", "DESCRIPCION": "CORREA PRUEBA", "NRO_LISTA_DE_PRECIOS": 10,
          "DESC_LISTA_DE_PRECIOS": "CLIENTE01", "PRECIO": 241.78, "MONEDA": False, "COD_CLIENTE": "CLI01",
          "RAZON_SOCIAL": "CLIENTE PRUEBA S.A.", "FECHA_MODIFICACION": "2026-09-17T18:38:18",
          "ID_STA11": 3655, "ID_GVA14": 660}


SALDO_ART = {"ID_STA11": 1, "ID_STA22": 1, "COD_ARTICULO": "1PAR00001", "DESCRIPCION": "11E108   O'Ring (2)",
             "DESCRIPCION_DEPOSITO": "CENTRAL", "UM_CONTROL_STOCK": "C/U", "SALDO_CONTROL_STOCK": -41,
             "CANTIDAD_COMPROMETIDA_CONTROL_STOCK": 2, "CANTIDAD_A_RECIBIR_CONTROL_STOCK": 0, "PUNTO_DE_PEDIDO": 0}


def _live(proceso):
    return {procesos.LIVE_PRECIOS_VIGENTES: [PRECIO], procesos.LIVE_SALDOS_POR_ARTICULO: [SALDO_ART]}.get(proceso, [SALDO])


class ClienteFalso:
    """Reemplaza al cliente HTTP: cuenta cuantas veces se le pidio cada proceso."""

    def __init__(self):
        self.llamadas = []

    def consulta_live(self, proceso, desde=None, hasta=None):
        self.llamadas.append((proceso, desde, hasta))
        return _live(proceso)

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

    def test_precio_vigente(self):
        p = PrecioVigente.desde_tango(PRECIO)
        self.assertEqual((p.numero_lista, p.lista, p.precio, p.moneda), (10, "CLIENTE01", 241.78, "US$"))
        self.assertEqual((p.codigo_cliente, p.modificado), ("CLI01", "2026-09-17"))
        sin_nombre = PrecioVigente.desde_tango({"NRO_LISTA_DE_PRECIOS": 3, "MONEDA": True})
        self.assertEqual((sin_nombre.lista, sin_nombre.moneda, sin_nombre.cliente), ("Lista 3", "$", ""))

    def test_cotizacion(self):
        c = Cotizacion.desde_tango({"TALONARIO": 128, "NRO_COTIZACION": " 0000100003215", "FECHA": "2026-11-16T00:00:00",
                                    "FECHA_DE_VIGENCIA": "2026-11-30T00:00:00", "ESTADO": 4, "MONEDA": False,
                                    "COD_CLIENTE": "CLI01", "RAZON_SOCIAL": "CLIENTE PRUEBA", "ID_GVA08": 18})
        self.assertEqual((c.numero_corto, c.estado_texto, c.moneda, c.vigencia), ("BA3215", "Procesada", "US$", "2026-11-30"))

    def test_remito_y_datos_de_envio(self):
        r = Remito.desde_tango({"TIPO_COMPROBANTE": "REM", "NRO_COMPROBANTE": "R0000800000110", "FECHA": "2026-11-14T00:00:00",
                                "COD_CLIENTE": "CLI01", "RAZON_SOCIAL": "CLIENTE PRUEBA", "ID_GVA14": 7, "ID_STA14": 31760})
        self.assertEqual(r.numero_corto, "R 00008-00000110")
        e = DatosEnvio.desde_tango({"COD_GVA14": "CLI01", "RAZON_SOCI": "CLIENTE PRUEBA", "CONTACTOS": [{"NOMBRE": "ANA", "DEFECTO": "S"}],
            "DIRECCION_ENTREGA": [
                {"COD_DIRECCION_ENTREGA": "DEP", "DIRECCION": "RUTA 1 ", "LOCALIDAD": "X", "COD_PROVINCIA": "02", "HABITUAL": "N"},
                {"COD_DIRECCION_ENTREGA": "PRINCIPAL", "DIRECCION": "CALLE 1", "LOCALIDAD": "Y", "COD_PROVINCIA": "02",
                 "HABITUAL": "S", "CODIGO_POSTAL": "7400"}]})
        self.assertEqual((e.direcciones[0].codigo, e.direcciones[0].provincia, e.contacto), ("PRINCIPAL", "Buenos Aires", "ANA"))
        sin = DatosEnvio.desde_tango({"RAZON_SOCI": "OTRO", "DOMICILIO": "AV 2", "LOCALIDAD": "Z", "C_POSTAL": "1000"})
        self.assertEqual(sin.direcciones[0].direccion, "AV 2")      # sin direcciones de entrega: el domicilio

    def test_remitos_con_oc_del_pedido(self):
        class Cliente(ClienteFalso):
            def consulta_live(self, proceso, desde=None, hasta=None):
                return [{"TIPO_COMPROBANTE": "REM", "NRO_COMPROBANTE": "R0000800000110", "FECHA": "2026-11-14T00:00:00"},
                        {"TIPO_COMPROBANTE": "FAC", "NRO_COMPROBANTE": "A0000300012358"}]
            def listar(self, proceso, vista=""):
                return [{**PEDIDO, "N_REMITO": " 0000800000110", "NRO_OC_COMP": "4500012345"}]
        remitos, _ = ServicioTango(Cliente()).remitos()
        self.assertEqual([(x.numero, x.orden_compra) for x in remitos], [("R0000800000110", "4500012345")])

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
        return _live(proceso)


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

    def test_configurar_con_la_direccion_del_programa(self):
        estado, datos = self._post("/api/sistema/configurar",
                                   {"servidor": f"http://127.0.0.1:{self.contexto.cfg.puerto}/", "token": TOKEN_OK})
        self.assertEqual(estado, 400)
        self.assertIn("17000", datos["mensaje"])

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

    def test_stock_por_articulo(self):
        estado, cuerpo = self._get("/api/stock/articulos")
        d = json.loads(cuerpo)["datos"][0]
        self.assertEqual(estado, 200)
        self.assertEqual((d["codigo_articulo"], d["saldo"], d["comprometido"], d["deposito"]), ("1PAR00001", -41, 2, "CENTRAL"))

    def test_pagina(self):
        estado, cuerpo = self._get("/")
        self.assertEqual(estado, 200)
        self.assertIn(b"app-nav", cuerpo)          # marco con la navegacion
        self.assertIn(b"/stock", cuerpo)
        estado, cuerpo = self._get("/stock")
        self.assertEqual(estado, 200)
        self.assertIn(b"Stock por partida", cuerpo)
        _, inicio = self._get("/")
        self.assertIn(b"<h1>Inicio</h1>", inicio)            # el inicio es el resumen
        estado, buscar = self._get("/buscar")
        self.assertEqual(estado, 200)
        self.assertIn(b"/etiqueta-codigo.js", buscar)       # codigo de barras en la ficha del articulo
        # Links viejos de Buscar (cuando estaba en el inicio) siguen andando
        _, viejo = self._get("/?q=zinc")
        self.assertIn(b"Buscar art", viejo)
        self.assertIn(b"/etiqueta-codigo.js", viejo)
        for archivo, texto in (("/codigo128.js", b"Codigo128"), ("/etiqueta-codigo.js", b"EtiquetaCodigo"),
                               ("/etiqueta-codigo.css", b"@page")):
            estado, cuerpo = self._get(archivo)
            self.assertEqual(estado, 200, archivo)
            self.assertIn(texto, cuerpo)

    def test_exportar_a_excel(self):
        from herramienta_tango import xlsx
        pedido = urllib.request.Request(self.base + "/api/exportar", method="POST", headers={"Content-Type": "application/json"},
            data=json.dumps({"nombre": "Stock ñandú", "columnas": [{"titulo": "Código"}, {"titulo": "Saldo", "tipo": "numero"}],
                             "filas": [["001", 2474.5], ["002", -41], ["003", None]]}).encode())
        with urllib.request.urlopen(pedido) as r:
            self.assertIn("spreadsheetml", r.headers["Content-Type"])
            self.assertIn("filename*=UTF-8''Stock%20%C3%B1and%C3%BA.xlsx", r.headers["Content-Disposition"])
            hojas = xlsx.leer(r.read())
        filas = list(hojas.values())[0]
        self.assertEqual(filas[:3], [["Código", "Saldo"], ["001", 2474.5], ["002", -41.0]])
        estado, datos = self._post("/api/exportar", {"columnas": "nada", "filas": []})
        self.assertEqual(estado, 400)
        self.assertFalse(datos["ok"])

    def test_movimientos_sin_base(self):
        # Fuera del servidor de Tango (o sin Windows) se explica por que no hay datos, sin romper
        estado, cuerpo = self._get("/api/articulos/01029071/movimientos")
        self.assertEqual(estado, 400)
        self.assertFalse(json.loads(cuerpo)["ok"])

    def test_pagina_importaciones(self):
        estado, cuerpo = self._get("/importaciones")
        self.assertEqual(estado, 200)
        self.assertIn(b"Carpetas de importaci", cuerpo)
        _, js = self._get("/comun.js")
        self.assertIn(b'grupo: "Importaciones"', js)
        estado, cuerpo = self._get("/api/importaciones")          # sin base (no es Windows): explica, no rompe
        self.assertEqual(estado, 400)
        self.assertFalse(json.loads(cuerpo)["ok"])

    def test_pagina_clientes(self):
        estado, cuerpo = self._get("/clientes")
        self.assertEqual(estado, 200)
        self.assertIn(b"<h1>Clientes</h1>", cuerpo)
        _, js = self._get("/comun.js")
        self.assertIn(b'href: "/clientes"', js)

    def test_cotizaciones_de_un_articulo(self):
        from herramienta_tango.tango.modelos import Cotizacion, RenglonCotizacion
        from herramienta_tango.web.servidor import cotizaciones_de_articulo

        def cot(id_, numero, fecha, estado):
            return Cotizacion.desde_tango({"ID_GVA08": id_, "NRO_COTIZACION": numero, "FECHA": fecha, "ESTADO": estado,
                                           "COD_CLIENTE": "CLI01", "RAZON_SOCIAL": "CLIENTE PRUEBA", "MONEDA": True})

        class Servicio:
            def cotizaciones(self, forzar=False):
                return [cot(1, "0000100003200", "2026-10-01", 4), cot(2, "0000100003215", "2026-11-16", 2)], 0.0
            def renglones_cotizaciones(self, forzar=False):
                r = lambda n, c, q: RenglonCotizacion.desde_tango({"NRO_COTIZACION": n, "COD_ARTICULO": c, "CANTIDAD": q, "PRECIO": 10})
                return [r("0000100003200", "ZINC ", 5), r("0000100003215", "ZINC", 7), r("0000100003215", "OTRO", 1),
                        r("0000199999999", "ZINC", 1)], 123.0     # la ultima no tiene cabecera: se ignora

        datos, momento = cotizaciones_de_articulo(Servicio(), "ZINC")
        self.assertEqual(momento, 123.0)
        self.assertEqual([(d["numero_corto"], d["cantidad"]) for d in datos], [("BA3215", 7), ("BA3200", 5)])   # nuevas primero
        estado, cuerpo = self._get("/api/articulos/ZINC/cotizaciones")
        self.assertEqual(estado, 200)
        self.assertTrue(json.loads(cuerpo)["ok"])

    def test_precios(self):
        estado, cuerpo = self._get("/api/precios")
        datos = json.loads(cuerpo)
        self.assertEqual(estado, 200)
        self.assertEqual(datos["datos"][0]["precio"], 241.78)
        estado, cuerpo = self._get("/precios")
        self.assertEqual(estado, 200)
        self.assertIn(b"Listas de precios", cuerpo)
        _, menu = self._get("/")
        self.assertIn(b"/precios", menu)

    def test_acceso_directo_para_otras_pcs(self):
        estado, cuerpo = self._get("/acceso-directo.url")
        self.assertEqual(estado, 200)
        texto = cuerpo.decode("ascii")
        self.assertTrue(texto.startswith("[InternetShortcut]"))
        self.assertIn(f":{self.contexto.cfg.puerto}/", texto)
        estado, _ = self._get("/icono.ico")
        self.assertEqual(estado, 200)
        estado, cuerpo = self._get("/manifest.json")
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(cuerpo)["start_url"], "/")

    def test_modo_servidor_fuera_de_windows(self):
        estado, datos = self._post("/api/sistema/modo-servidor", {"activo": True})
        self.assertEqual(estado, 400)
        self.assertFalse(datos["ok"])
        self.assertIn("modo_servidor", datos["sistema"])

    def test_archivos_comunes(self):
        for ruta, tipo in (("/comun.js", "text/javascript"), ("/comun.css", "text/css")):
            with urllib.request.urlopen(self.base + ruta) as r:
                self.assertTrue(r.headers["Content-Type"].startswith(tipo), ruta)

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


class TestModoServidor(unittest.TestCase):
    def test_script_activar(self):
        from herramienta_tango import sistema
        inst = sistema.Instalacion(Path("C:/Herramienta Tango"), Path("C:/Herramienta Tango/python/pythonw.exe"),
                                   Path("C:/Herramienta Tango/app/HerramientaTango.pyw"), Path("C:/x.ico"))
        script = sistema.script_activar_servidor(inst, 8085, 1234)
        self.assertIn("--servicio", script)
        self.assertIn("-LocalPort 8085", script)
        self.assertIn("Wait-Process -Id 1234", script)
        self.assertIn("'192.168.0.0/16'", script)
        self.assertIn("-ExecutionTimeLimit ([TimeSpan]::Zero)", script)

    def test_vigilante_reabre_y_se_detiene(self):
        from herramienta_tango import app
        codigos = iter([app.SALIDA_REINICIAR, 1, app.SALIDA_DETENER])
        with mock.patch.object(app.subprocess, "call", side_effect=lambda *a, **k: next(codigos)) as llamada, \
             mock.patch.object(app.time, "sleep") as dormir:
            self.assertEqual(app._vigilar(), 0)
        app.sistema.SIN_AVISOS = False
        self.assertEqual(llamada.call_count, 3)
        self.assertEqual(dormir.call_count, 1)   # solo espera despues del error
        self.assertIn("--hijo-servicio", llamada.call_args[0][0])


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
