"""El cliente sigue andando cuando Windows no resuelve el nombre de la PC de Tango."""

import io
import json
import socket
import unittest
import urllib.error
from unittest import mock

from herramienta_tango.tango import cliente as mod


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _urlopen_que_falla_con(host_caido):
    vistos = []

    def abrir(pedido, timeout=None):
        vistos.append(pedido.full_url)
        if f"//{host_caido}" in pedido.full_url:
            raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
        return _Resp(json.dumps({"succeeded": True, "resultData": {"list": [{"a": 1}], "totalPages": 1}}).encode())
    return abrir, vistos


class NombreNoResuelto(unittest.TestCase):
    def setUp(self):
        mod._ips_conocidas.clear()
        p = mock.patch.object(mod, "_ruta_ips", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def test_usa_la_ip_que_ya_anduvo(self):
        mod._ips_conocidas["desktop-b11ba4h"] = "192.168.0.20"
        abrir, vistos = _urlopen_que_falla_con("desktop-b11ba4h")
        c = mod.ClienteTango("http://desktop-b11ba4h:17000", "3", "t")
        with mock.patch.object(mod.urllib.request, "urlopen", abrir), \
             mock.patch.object(mod.socket, "gethostname", return_value="otra-pc"):
            self.assertEqual(c.listar(87), [{"a": 1}])
            c.listar(87)   # la segunda va directo a la IP, sin esperar otra falla
        self.assertTrue(vistos[1].startswith("http://192.168.0.20:17000/api/Get"))
        self.assertEqual(sum("desktop-b11ba4h" in u for u in vistos), 1)

    def test_si_es_esta_pc_usa_localhost(self):
        abrir, vistos = _urlopen_que_falla_con("desktop-b11ba4h")
        c = mod.ClienteTango("http://desktop-b11ba4h:17000", "3", "t")
        with mock.patch.object(mod.urllib.request, "urlopen", abrir), \
             mock.patch.object(mod.socket, "gethostname", return_value="DESKTOP-B11BA4H"):
            self.assertEqual(c.listar(87), [{"a": 1}])
        self.assertTrue(vistos[-1].startswith("http://127.0.0.1:17000/"))

    def test_sin_alternativa_explica_que_hacer(self):
        abrir, _ = _urlopen_que_falla_con("desktop-b11ba4h")
        c = mod.ClienteTango("http://desktop-b11ba4h:17000", "3", "t")
        with mock.patch.object(mod.urllib.request, "urlopen", abrir), \
             mock.patch.object(mod.socket, "gethostname", return_value="otra-pc"), \
             self.assertRaises(mod.SinConexion) as ctx:
            c.listar(87)
        self.assertIn("no encuentra la computadora «desktop-b11ba4h»", str(ctx.exception))
        self.assertIn("IP", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
