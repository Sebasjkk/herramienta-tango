"""Cache que se renueva sola y paginas pedidas en paralelo."""

import threading
import time
import unittest
from unittest import mock

from herramienta_tango.tango import cliente as mod_cliente
from herramienta_tango.tango.servicio import _Cache


class CacheRenovable(unittest.TestCase):
    def test_vencido_devuelve_lo_guardado_y_renueva_aparte(self):
        c = _Cache()
        c.obtener("k", 60, lambda: "viejo")
        momento_viejo = c._datos["k"][0]
        c._datos["k"] = (momento_viejo - 120, "viejo")       # vencio hace 1 minuto
        listo = threading.Event()

        def lento():
            listo.wait(2)
            return "nuevo"
        inicio = time.time()
        datos, _ = c.obtener("k", 60, lento)
        self.assertEqual(datos, "viejo")
        self.assertLess(time.time() - inicio, 0.5, "no tiene que esperar a Tango")
        listo.set()
        for _ in range(100):
            if c._datos["k"][1] == "nuevo":
                break
            time.sleep(0.02)
        self.assertEqual(c.obtener("k", 60, lambda: "otro")[0], "nuevo")

    def test_muy_viejo_espera_lo_nuevo(self):
        c = _Cache()
        c._datos["k"] = (time.time() - 60 * 60, "de hace una hora")
        self.assertEqual(c.obtener("k", 60, lambda: "nuevo")[0], "nuevo")

    def test_falla_en_segundo_plano_deja_lo_anterior(self):
        c = _Cache()
        c._datos["k"] = (time.time() - 120, "anterior")

        def falla():
            raise RuntimeError("Tango caído")
        self.assertEqual(c.obtener("k", 60, falla)[0], "anterior")
        time.sleep(0.1)
        self.assertEqual(c._datos["k"][1], "anterior")


class PaginasEnParalelo(unittest.TestCase):
    def test_trae_todo_en_orden(self):
        c = mod_cliente.ClienteTango("http://x:17000", "3", "t")
        c.TAM_PAGINA = 2

        def get(ruta, p):
            n = p["pageIndex"]
            time.sleep(0.05 * (5 - n))      # las ultimas contestan antes
            return {"resultData": {"list": [n * 2, n * 2 + 1], "totalPages": 5}}
        with mock.patch.object(c, "_get", side_effect=get):
            self.assertEqual(c.listar(87), list(range(10)))


if __name__ == "__main__":
    unittest.main()
