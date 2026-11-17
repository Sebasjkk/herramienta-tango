"""
Pruebas del editor de listas de precios y de la clave para modificarlos, con un
Tango falso en memoria que se comporta como el real (probado el 17/11/2026):
los precios especiales por cliente (GVA13) viajan adentro del renglon (GVA17).
"""

import copy
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from herramienta_tango import autorizacion, config
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
        self.escrituras = []
        self._sig = 2000

    def _tabla(self, proceso):
        return self.listas if proceso == 984 else self.renglones

    def listar(self, proceso, vista=""):
        if proceso == 984:
            return [copy.deepcopy(x) for x in self.listas.values()]
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
        clave = "ID_GVA10" if proceso == 984 else "ID_GVA17"
        self._tabla(proceso)[registro[clave]] = copy.deepcopy(registro)
        self.escrituras.append(("actualizar", proceso, registro[clave], len(registro.get("GVA13") or [])))

    def borrar(self, proceso, id_registro):
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

    def test_precios_de_articulo(self):
        ps = self.editor.precios_de_articulo("0039812")
        self.assertEqual([(p["lista"], p["especiales"][0]["razon_social"]) for p in ps], [("SCIPIO", "SCIPIO S.A.")])


class TestPerfiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.usuarios = autorizacion.Usuarios(Path(self.tmp.name) / "usuarios.json")
        self.sesiones = autorizacion.Sesiones(self.usuarios)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sin_perfiles_no_se_entra(self):
        token, mensaje = self.sesiones.entrar("Gustavo", "lo-que-sea", "10.0.0.5")
        self.assertIsNone(token)
        self.assertIn("panel", mensaje)

    def test_perfiles(self):
        admin = self.usuarios.crear("Sebastián", "clave-admin", "administrador", debe_cambiar=False)
        for n in ("Estela", "Gustavo", "Francisco"):
            self.usuarios.crear(n, "inicial123")
        self.assertEqual(self.usuarios.nombres(), ["Estela", "Francisco", "Gustavo", "Sebastián"])
        with self.assertRaises(autorizacion.PedidoInvalido):
            self.usuarios.crear("gustavo", "otra-clave")          # repetido
        with self.assertRaises(autorizacion.PedidoInvalido):
            self.usuarios.crear("Ana", "corta")                   # clave corta
        self.assertNotIn("inicial123", self.usuarios.ruta.read_text(encoding="utf-8"))

        self.assertIsNone(self.sesiones.entrar("Gustavo", "mal-clave", "10.0.0.5")[0])
        token, _ = self.sesiones.entrar("gustavo", "inicial123", "10.0.0.5")
        u = self.sesiones.usuario(token)
        self.assertEqual((u["nombre"], u["rol"], u["debe_cambiar"]), ("Gustavo", "usuario", True))
        with self.assertRaises(autorizacion.PedidoInvalido):
            self.usuarios.cambiar_clave_propia(u["id"], "mal", "nueva-clave")
        self.usuarios.cambiar_clave_propia(u["id"], "inicial123", "nueva-clave")
        self.assertFalse(self.sesiones.usuario(token)["debe_cambiar"])

        # Tiene que quedar un administrador
        with self.assertRaises(autorizacion.PedidoInvalido):
            self.usuarios.cambiar_rol(admin["id"], "usuario")
        with self.assertRaises(autorizacion.PedidoInvalido):
            self.usuarios.eliminar(admin["id"])
        # Eliminado: la sesion deja de valer
        self.usuarios.eliminar(u["id"])
        self.assertIsNone(self.sesiones.usuario(token))


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

    def _entrar(self, nombre, clave):
        estado, d = self._pedir("/api/sesion", {"nombre": nombre, "clave": clave})
        self.assertEqual(estado, 200, d)
        return {"X-Sesion": d["token"]}

    def test_circuito(self):
        # Sin sesion no se modifica nada
        estado, _ = self._pedir("/api/precios/cambiar", {"renglon": 10, "precio": 5})
        self.assertEqual(estado, 401)
        # El primer administrador se crea desde el panel (misma PC)
        estado, d = self._pedir("/api/sistema/administrador", {"nombre": "Sebastián", "clave": "clave-admin"},
                                {"X-Herramienta-Tango": "1"})
        self.assertEqual(estado, 200, d)
        admin = self._entrar("Sebastián", "clave-admin")
        # El administrador crea los perfiles con la misma clave inicial
        for n in ("Estela", "Gustavo", "Francisco"):
            estado, d = self._pedir("/api/usuarios/crear", {"nombre": n, "clave": "inicial123"}, admin)
            self.assertEqual(estado, 200, d)
        estado, d = self._pedir("/api/sesion")
        self.assertEqual(d["nombres"], ["Estela", "Francisco", "Gustavo", "Sebastián"])

        gustavo = self._entrar("Gustavo", "inicial123")
        estado, d = self._pedir("/api/precios/cambiar", {"renglon": 1351, "precio": 260, "cliente": 660}, gustavo)
        self.assertEqual(estado, 403)                          # primero tiene que cambiar la clave
        estado, d = self._pedir("/api/sesion/clave", {"actual": "inicial123", "nueva": "gustavo2026"}, gustavo)
        self.assertEqual(estado, 200, d)
        estado, d = self._pedir("/api/precios/cambiar", {"renglon": 1351, "precio": 260, "cliente": 660}, gustavo)
        self.assertEqual(estado, 200, d)
        self.assertEqual(self.tango.renglones[1351]["GVA13"][0]["PRECIO"], 260)
        # Un usuario comun no crea listas ni maneja perfiles
        estado, _ = self._pedir("/api/listas/crear", {"nombre": "X", "moneda": "$"}, gustavo)
        self.assertEqual(estado, 403)
        estado, _ = self._pedir("/api/usuarios", None, gustavo)
        self.assertEqual(estado, 403)
        estado, d = self._pedir("/api/precios/cambios")
        self.assertEqual(d["datos"][0]["quien"], "Gustavo")
