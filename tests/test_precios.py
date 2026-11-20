"""
Pruebas del editor de listas de precios y de la clave para modificarlos, con un
Tango falso en memoria que se comporta como el real (probado el 17/11/2026):
los precios especiales por cliente (GVA13) viajan adentro del renglon (GVA17).
"""

import copy
import json
import tempfile
import time
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from herramienta_tango import config
from herramienta_tango.tango import TangoError
from herramienta_tango.precios import EditorPrecios, PedidoInvalido, RegistroCambios
from herramienta_tango.tango.modelos import Articulo, Cliente


def lista(i, nro, nombre, mon_cte=False):
    return {"GVA10_PARAMETROS_AUTOMATIZACION": [], "CTA_LISTA_VENTA_POR_SUCURSAL": [], "ID_GVA10": i,
            "NRO_DE_LIS": nro, "NOMBRE_LIS": nombre, "HABILITADA": True, "MON_CTE": mon_cte, "DECIMALES": 2,
            "INCLUY_IVA": False, "INCLUY_IMP": False, "FEC_DESDE": None, "FEC_HASTA": None,
            "OBSERVACIONES": None, "COD_DESCRIP": f"{nro} - {nombre}"}


def renglon(i, id_lista, nro, art_id, art, precio, especiales=()):
    return {"ID_STA11": art_id, "DECIMALES_RESTO": None, "DECIMALES_GVA17": 2, "ID_GVA17": i, "NRO_DE_LIS": nro,
            "COD_ARTICU": art, "ID_GVA10": id_lista, "PRECIO": precio, "BASE": False, "ID_MAESTRO_GVA17": 1, "FILLER": "",
            "GVA13": [{"ACTUALIZAR_CONTROL_PRECIOS": False, "ID_GVA13": 100 + i, "ID_GVA10": id_lista, "ID_STA11": art_id,
                       "ID_GVA14": cli_id, "FILLER": "", "COD_ARTICU": art, "COD_CLIENT": cli, "NRO_LISTA": nro,
                       "PRECIO": p, "ID_GVA17": i} for cli_id, cli, p in especiales]}


class TangoFalso:
    """Guarda listas (984) y renglones (20091) en memoria."""

    def __init__(self):
        self.listas = {1: lista(1, 1, "METCO", True), 6: lista(6, 10, "SCIPIO")}
        self.renglones = {
            10: renglon(10, 1, 1, 501, "1PAR00001", 3.82),
            1351: renglon(1351, 6, 10, 3655, "0039812", 0, [(660, "SCIPIO", 241.78)]),
            1352: renglon(1352, 6, 10, 3656, "0039813", 0, [(660, "SCIPIO", 241.78)]),
        }
        # Fichas de clientes (2117): la lista va en ID_GVA10 y NRO_LISTA
        self.fichas = {309: {"ID_GVA14": 309, "COD_GVA14": "AERARG", "RAZON_SOCI": "AEROLINEAS ARG", "ID_GVA10": 1,
                             "NRO_LISTA": 1, "FECHA_MODI": "2019-08-07T15:33:34", "DIRECCION_ENTREGA": [{"ID": 1}]}}
        self.pedidos = {24: {"ID_GVA21": 24, "NRO_PEDIDO": " 0000000000037", "ID_GVA10": 1}}   # usa METCO
        self.escrituras = []
        self._sig = 2000

    _CLAVES = {984: "ID_GVA10", 20091: "ID_GVA17", 2117: "ID_GVA14", 19845: "ID_GVA21"}

    def _tabla(self, proceso):
        return {984: self.listas, 2117: self.fichas, 19845: self.pedidos}.get(proceso, self.renglones)

    def listar(self, proceso, vista=""):
        if proceso in (984, 19845):
            return [copy.deepcopy(x) for x in self._tabla(proceso).values()]
        salida = []
        for r in self.renglones.values():
            x = {k: v for k, v in r.items() if k not in ("GVA13", "COD_ARTICU")}
            x.update(COD_STA11=r["COD_ARTICU"], DESCRIPCIO=f"DESC {r['COD_ARTICU']}",
                     NOMBRE_LIS=self.listas[r["ID_GVA10"]]["NOMBRE_LIS"], FECHA_MODI=None,
                     MONEDA_CORRIENTE="USD - Dolares")
            salida.append(x)
        return salida

    def obtener(self, proceso, id_registro):
        x = self._tabla(proceso).get(id_registro)
        return copy.deepcopy(x) if x else None

    def crear(self, proceso, registro):
        self._sig += 1
        clave = "ID_GVA10" if proceso == 984 else "ID_GVA17"
        self._tabla(proceso)[self._sig] = {**copy.deepcopy(registro), clave: self._sig}
        self.escrituras.append(("crear", proceso, self._sig))
        return self._sig

    def actualizar(self, proceso, registro):
        clave = self._CLAVES[proceso]
        if proceso == 2117:
            registro = {**registro, "FECHA_MODI": "2026-11-19T07:44:24"}
        self._tabla(proceso)[registro[clave]] = copy.deepcopy(registro)
        self.escrituras.append(("actualizar", proceso, registro[clave], len(registro.get("GVA13") or [])))

    rechazar_borrar_lista = ""

    def borrar(self, proceso, id_registro):
        if proceso == 984 and self.rechazar_borrar_lista:
            raise TangoError(f"Tango no pudo resolver el pedido: {self.rechazar_borrar_lista}")
        self._tabla(proceso).pop(id_registro, None)
        self.escrituras.append(("borrar", proceso, id_registro))


class ServicioFalso:
    def __init__(self, clientes=()):
        self._clientes = list(clientes)

    def clientes(self, forzar=False):
        return self._clientes, 0

    def articulos(self, forzar=False):
        a = lambda i, c: Articulo(i, c, f"DESC {c}", "", "", "", True, True, "", "KG", "", 0, 0, 0)
        return [a(501, "1PAR00001"), a(3655, "0039812"), a(3656, "0039813"), a(3700, "1000125")], 0

    def olvidar(self, clave):
        pass


def cliente(codigo, lista_nombre):
    return Cliente(id=660, codigo=codigo, razon_social=f"{codigo} S.A.", cuit="", habilitado=True, lista_precios=lista_nombre)


class TestEditor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tango = TangoFalso()
        self.registro = RegistroCambios(Path(self.tmp.name) / "cambios.jsonl")
        self.editor = EditorPrecios(self.tango, ServicioFalso([cliente("SCIPIO", "SCIPIO")]), self.registro)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lista_de_cliente_trae_especiales_y_dueno(self):
        d = self.editor.lista(6)
        self.assertEqual(d["cliente"]["codigo"], "SCIPIO")
        self.assertEqual(d["renglones"][0]["especiales"][0]["precio"], 241.78)
        self.assertEqual(d["renglones"][0]["precio"], 0)

    def test_listas_con_clientes_asignados(self):
        ls = {l["nombre"]: l for l in self.editor.listas()}
        self.assertEqual(ls["SCIPIO"]["articulos"], 2)
        self.assertEqual(ls["SCIPIO"]["clientes_asignados"], ["SCIPIO S.A."])
        self.assertEqual(ls["METCO"]["moneda"], "$")

    def test_cambiar_precio_especial(self):
        r = self.editor.cambiar_precio(1351, "250,5", "Gustavo", id_cliente=660)
        self.assertEqual(r["despues"]["especiales"][0]["precio"], 250.5)
        self.assertEqual(self.tango.renglones[1351]["PRECIO"], 0)          # el de lista no se toca
        cambio = self.registro.ultimos()[0]
        self.assertEqual((cambio["quien"], cambio["accion"]), ("Gustavo", "cambiar precio"))
        self.assertEqual(cambio["antes"]["especiales"][0]["precio"], 241.78)

    def test_cambiar_precio_de_lista(self):
        self.editor.cambiar_precio(10, 4, "Gustavo")
        self.assertEqual(self.tango.renglones[10]["PRECIO"], 4)

    def test_precio_invalido(self):
        for malo in ("abc", -1):
            with self.assertRaises(PedidoInvalido):
                self.editor.cambiar_precio(10, malo, "Gustavo")
        self.assertEqual(self.tango.escrituras, [])

    def test_agregar_a_lista_de_cliente_va_como_especial(self):
        r = self.editor.agregar_articulo(6, "1000125", 100, "Gustavo")
        nuevo = self.tango.renglones[r["id"]]
        self.assertEqual(nuevo["PRECIO"], 0)
        self.assertEqual([(c["COD_CLIENT"], c["PRECIO"]) for c in nuevo["GVA13"]], [("SCIPIO", 100)])

    def test_agregar_a_lista_general_va_como_precio_de_lista(self):
        r = self.editor.agregar_articulo(1, "1000125", 7.5, "Gustavo")
        nuevo = self.tango.renglones[r["id"]]
        self.assertEqual((nuevo["PRECIO"], nuevo["GVA13"]), (7.5, []))

    def test_agregar_repetido_o_inexistente(self):
        with self.assertRaises(PedidoInvalido):
            self.editor.agregar_articulo(6, "0039812", 1, "Gustavo")
        with self.assertRaises(PedidoInvalido):
            self.editor.agregar_articulo(6, "NO-EXISTE", 1, "Gustavo")

    def test_quitar_saca_primero_los_especiales(self):
        self.editor.quitar_articulo(1351, "Gustavo")
        self.assertNotIn(1351, self.tango.renglones)
        self.assertEqual(self.tango.escrituras, [("actualizar", 20091, 1351, 0), ("borrar", 20091, 1351)])

    def test_crear_lista(self):
        r = self.editor.crear_lista("nuevo cliente", "US$", "Gustavo")
        self.assertEqual((r["numero"], r["nombre"]), (11, "NUEVO CLIENTE"))
        creada = self.tango.listas[r["id"]]
        self.assertFalse(creada["MON_CTE"])
        with self.assertRaises(PedidoInvalido):
            self.editor.crear_lista("Nuevo Cliente", "$", "Gustavo")      # nombre repetido
        with self.assertRaises(PedidoInvalido):
            self.editor.crear_lista("OTRA", "$", "Gustavo", numero=10)    # numero repetido

    def test_eliminar_lista_asignada_no_se_puede(self):
        with self.assertRaises(PedidoInvalido):
            self.editor.eliminar_lista(6, "SCIPIO", "Gustavo")
        self.assertIn(6, self.tango.listas)

    def test_eliminar_lista(self):
        editor = EditorPrecios(self.tango, ServicioFalso(), self.registro)
        with self.assertRaises(PedidoInvalido):
            editor.eliminar_lista(6, "SCIPI", "Gustavo")                  # nombre mal escrito
        r = editor.eliminar_lista(6, "scipio", "Gustavo")
        self.assertEqual(r["articulos_quitados"], 2)
        self.assertNotIn(6, self.tango.listas)
        self.assertFalse(any(x["ID_GVA10"] == 6 for x in self.tango.renglones.values()))
        self.assertEqual(len(self.registro.ultimos()[0]["contenido"]), 2)   # queda copia de lo borrado

    def test_no_elimina_una_lista_con_pedidos(self):
        editor = EditorPrecios(self.tango, ServicioFalso(), self.registro)
        self.tango.pedidos[24]["ID_GVA10"] = 6                                # el pedido 37 usa SCIPIO
        antes = len(self.tango.renglones)
        with self.assertRaisesRegex(PedidoInvalido, "1 pedido en Tango.*37.*No se tocó nada"):
            editor.eliminar_lista(6, "SCIPIO", "Gustavo")
        self.assertEqual((len(self.tango.renglones), self.tango.escrituras), (antes, []))
        # Anulado: ya no frena de antemano. Si Tango rechaza por pedidos, no se toca nada.
        self.tango.pedidos[24]["ESTADO"] = 5
        self.tango.rechazar_borrar_lista = "No es posible eliminar el registro porque existen datos relacionados en Pedidos."
        with self.assertRaisesRegex(TangoError, "Aunque estén anulados.*No se tocó nada"):
            editor.eliminar_lista(6, "SCIPIO", "Gustavo")
        self.assertEqual(len(self.tango.renglones), antes)
        # Si Tango la deja borrar, se borra con sus articulos
        self.tango.rechazar_borrar_lista = ""
        editor.eliminar_lista(6, "SCIPIO", "Gustavo")
        self.assertNotIn(6, self.tango.listas)
        self.assertFalse(any(r["ID_GVA10"] == 6 for r in self.tango.renglones.values()))

    def test_restaurar_lista_eliminada(self):
        # el cliente SCIPIO ya usa otra lista, pero sus precios especiales siguen en la copia
        editor = EditorPrecios(self.tango, ServicioFalso([cliente("SCIPIO", "METCO")]), self.registro)
        self.tango.rechazar_borrar_lista = "La lista tiene comprobantes asociados"
        originales = {r["COD_ARTICU"]: (r["PRECIO"], [c["PRECIO"] for c in r["GVA13"]])
                      for r in self.tango.renglones.values() if r["ID_GVA10"] == 6}
        with self.assertRaises(TangoError):
            editor.eliminar_lista(6, "SCIPIO", "Gustavo")
        self.assertFalse(any(r["ID_GVA10"] == 6 for r in self.tango.renglones.values()))   # quedo vacia
        copia = next(c for c in self.registro.ultimos() if c["accion"] == "eliminar lista")
        editor.restaurar_lista(copia["fecha"], "SCIPIO", "Gustavo")
        for _ in range(200):
            if not editor.estado_restauracion()["corriendo"]:
                break
            time.sleep(0.02)
        estado = editor.estado_restauracion()
        self.assertEqual((estado["hechos"], estado["errores"]), (2, []))
        ahora = {r["COD_ARTICU"]: (r["PRECIO"], [c["PRECIO"] for c in r["GVA13"]])
                 for r in self.tango.renglones.values() if r["ID_GVA10"] == 6}
        self.assertEqual(ahora, originales)
        editor.restaurar_lista(copia["fecha"], "SCIPIO", "Gustavo")         # otra vez: no duplica
        for _ in range(200):
            if not editor.estado_restauracion()["corriendo"]:
                break
            time.sleep(0.02)
        self.assertEqual(editor.estado_restauracion()["ya_estaban"], 2)

    def test_eliminar_lista_que_tango_rechaza(self):
        editor = EditorPrecios(self.tango, ServicioFalso(), self.registro)
        self.tango.rechazar_borrar_lista = "La lista tiene comprobantes asociados"
        with self.assertRaisesRegex(TangoError, "comprobantes asociados.*quitado 2 de sus 2.*eliminala desde Tango"):
            editor.eliminar_lista(6, "SCIPIO", "Gustavo")
        self.assertIn(6, self.tango.listas)
        error, copia = self.registro.ultimos()[:2]
        self.assertEqual(error["accion"], "error al eliminar lista")
        self.assertEqual(copia["accion"], "eliminar lista")
        self.assertEqual(len(copia["contenido"]), 2)                         # la copia quedo guardada antes

    def test_obtener_registro_inexistente_es_none(self):
        from herramienta_tango.tango.cliente import ClienteTango
        c = ClienteTango.__new__(ClienteTango)
        respuestas = [{"succeeded": False, "message": "Se detectó una situación inesperada",
                       "exceptionInfo": {"messages": ["Registro inexistente."]}},
                      {"succeeded": False, "exceptionInfo": {"messages": ["Otro error"]}}]

        def falso(metodo, ruta, parametros, cuerpo=None):
            d = respuestas.pop(0)
            raise TangoError(f"Tango no pudo resolver el pedido: {d['exceptionInfo']['messages'][0]}")
        c._pedir = falso
        self.assertIsNone(c.obtener(20091, 5))
        with self.assertRaisesRegex(TangoError, "Otro error"):
            c.obtener(20091, 5)

    def test_motivo_del_error_de_tango(self):
        from herramienta_tango.tango.cliente import _motivo
        datos = {"message": "Se detectó una situación inesperada", "succeeded": False,
                 "exceptionInfo": {"title": "Atención", "messages": ["Su licencia no incluye el uso del API"],
                                   "detailMessages": [{"message": "Detalle  extra"}]}}
        self.assertEqual(_motivo(datos), "Su licencia no incluye el uso del API Detalle extra")
        self.assertEqual(_motivo({"message": "Algo"}), "Algo")

    def test_eliminar_lista_cambiando_la_del_cliente(self):
        tango = self.tango

        class ServicioConFichas(ServicioFalso):
            """Los clientes salen de las fichas: cuando cambia la ficha, cambia su lista."""
            def clientes(self, forzar=False):
                return [Cliente(id=i, codigo=f["COD_GVA14"], razon_social=f["RAZON_SOCI"], cuit="", habilitado=True,
                                lista_precios=tango.listas[f["ID_GVA10"]]["NOMBRE_LIS"]) for i, f in tango.fichas.items()], 0

        tango.fichas[309].update(ID_GVA10=6, NRO_LISTA=10)                 # AERARG usa SCIPIO
        editor = EditorPrecios(tango, ServicioConFichas(), self.registro)
        with self.assertRaisesRegex(PedidoInvalido, "AEROLINEAS ARG"):
            editor.eliminar_lista(6, "SCIPIO", "Gustavo")                  # sin lista nueva: se niega
        with self.assertRaises(PedidoInvalido):
            editor.eliminar_lista(6, "SCIPIO", "Gustavo", reasignar_a=6)   # la misma no vale
        r = editor.eliminar_lista(6, "SCIPIO", "Gustavo", reasignar_a=1)
        self.assertEqual(r["clientes_reasignados"], ["AEROLINEAS ARG"])
        self.assertEqual((tango.fichas[309]["ID_GVA10"], tango.fichas[309]["NRO_LISTA"]), (1, 1))
        self.assertNotIn(6, tango.listas)
        acciones = [c["accion"] for c in self.registro.ultimos()]
        self.assertEqual(acciones[:2], ["eliminar lista", "asignar lista"])

    def test_asignar_lista_a_cliente(self):
        r = self.editor.asignar_lista(6, 309, "Estela")
        ficha = self.tango.fichas[309]
        self.assertEqual((ficha["ID_GVA10"], ficha["NRO_LISTA"]), (6, 10))
        self.assertEqual(ficha["DIRECCION_ENTREGA"], [{"ID": 1}])        # se manda la ficha entera
        self.assertEqual(r["anterior"], "METCO")
        c = self.registro.ultimos()[0]
        self.assertEqual((c["accion"], c["cliente"], c["lista_anterior"], c["lista"]), ("asignar lista", "AERARG", "METCO", "SCIPIO"))
        n = len(self.tango.escrituras)
        self.assertTrue(self.editor.asignar_lista(6, 309, "Estela")["sin_cambios"])   # ya la tiene: no escribe
        self.assertEqual(len(self.tango.escrituras), n)
        with self.assertRaises(PedidoInvalido):
            self.editor.asignar_lista(6, 999, "Estela")                   # cliente que no existe

    def test_crear_lista_para_un_cliente(self):
        r = self.editor.crear_lista("aerarg", "US$", "Estela", id_cliente=309)
        self.assertEqual(self.tango.fichas[309]["ID_GVA10"], r["id"])
        self.assertEqual(self.tango.fichas[309]["NRO_LISTA"], r["numero"])
        self.assertEqual(r["asignada"]["anterior"], "METCO")

    def test_precios_de_articulo(self):
        ps = self.editor.precios_de_articulo("0039812")
        self.assertEqual([(p["lista"], p["especiales"][0]["razon_social"]) for p in ps], [("SCIPIO", "SCIPIO S.A.")])


class TestServidorPrecios(unittest.TestCase):
    """Perfiles y modificaciones por HTTP, contra el editor con el Tango falso."""

    @classmethod
    def setUpClass(cls):
        from herramienta_tango.contexto import Contexto
        from herramienta_tango.web.servidor import crear_servidor
        from test_herramienta import CFG

        cls.tmp = tempfile.TemporaryDirectory()
        cls.parches = [mock.patch.object(config, "CARPETA", Path(cls.tmp.name)),
                       mock.patch.object(config, "RUTA_CONFIG", Path(cls.tmp.name) / "config.ini")]
        for p in cls.parches:
            p.start()
        cls.tango = TangoFalso()
        servicio = ServicioFalso()
        servicio.editor = EditorPrecios(cls.tango, servicio, RegistroCambios(Path(cls.tmp.name) / "c.jsonl"))
        cls.contexto = Contexto(CFG)
        cls.contexto._servicio = servicio
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

    def _pedir(self, ruta, datos=None, encabezados=None):
        pedido = urllib.request.Request(self.base + ruta, method="POST" if datos is not None else "GET",
                                        data=json.dumps(datos).encode() if datos is not None else None,
                                        headers={"Content-Type": "application/json", **(encabezados or {})})
        try:
            with urllib.request.urlopen(pedido) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_circuito(self):
        # Cualquiera de la red modifica; el nombre (si lo hay) va al registro con la IP
        estado, d = self._pedir("/api/precios/cambiar", {"renglon": 1351, "precio": 260, "cliente": 660},
                                {"X-Nombre": "Gustavo%20Ruiz"})
        self.assertEqual(estado, 200, d)
        self.assertEqual(self.tango.renglones[1351]["GVA13"][0]["PRECIO"], 260)
        estado, d = self._pedir("/api/precios/cambiar", {"renglon": 1351, "precio": "x", "cliente": 660})
        self.assertEqual(estado, 400)
        estado, d = self._pedir("/api/listas/6")
        self.assertEqual(d["datos"]["cliente"]["codigo"], "SCIPIO")
        estado, d = self._pedir("/api/precios/cambios")
        self.assertEqual(d["datos"][0]["quien"], "Gustavo Ruiz (127.0.0.1)")
        estado, d = self._pedir("/api/listas/asignar", {"lista": 6, "cliente": 309})
        self.assertEqual(estado, 200, d)
        self.assertEqual(self.tango.fichas[309]["NRO_LISTA"], 10)
        estado, _ = self._pedir("/api/listas/asignar", {"lista": 6})
        self.assertEqual(estado, 400)
        estado, _ = self._pedir("/api/sesion")
        self.assertEqual(estado, 404)                        # ya no hay perfiles
