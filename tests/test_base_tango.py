"""Pruebas de la lectura de la base de Tango (sin SQL real: se simula PowerShell)."""
import subprocess
import unittest
from unittest import mock

from herramienta_tango import base_tango


def salida(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


class TestBaseTango(unittest.TestCase):
    def setUp(self):
        base_tango._cache.clear()
        p = mock.patch.object(base_tango.sys, "platform", "win32"); p.start(); self.addCleanup(p.stop)

    def test_fuera_de_windows(self):
        with mock.patch.object(base_tango.sys, "platform", "linux"):
            with self.assertRaises(base_tango.BaseNoDisponible):
                base_tango.usos_lista(2, 6)

    def test_lee_y_normaliza(self):
        js = '{"cotizaciones":{"numero":"BA3213"},"cotizaciones_total":1,"facturas_por_anio":null}'
        with mock.patch.object(base_tango.subprocess, "run", return_value=salida("aviso\n" + js)) as run:
            d = base_tango.usos_lista("2", "6")
        self.assertEqual(d["cotizaciones"], [{"numero": "BA3213"}])     # una sola fila llega como objeto
        self.assertEqual(d["facturas_por_anio"], [])
        script = run.call_args[0][0][-1]
        self.assertIn("WHERE q.ID_GVA10 = 2", script)
        self.assertIn("NRO_DE_LIS = 6", script)
        self.assertNotIn("INSERT", script.upper().replace("INSERTAR", ""))
        with mock.patch.object(base_tango.subprocess, "run") as run2:     # segunda vez sale de la cache
            base_tango.usos_lista(2, 6)
        run2.assert_not_called()

    def test_ids_solo_enteros(self):
        with self.assertRaises(ValueError):
            base_tango.usos_lista("2; DROP TABLE GVA10", 6)

    def test_sin_permiso(self):
        with mock.patch.object(base_tango.subprocess, "run",
                               return_value=salida(stderr="Login failed for user 'NT AUTHORITY\\SYSTEM'.", rc=1)):
            with self.assertRaisesRegex(base_tango.BaseNoDisponible, "permiso"):
                base_tango.usos_lista(2, 6)

    def test_powershell_falla(self):
        with mock.patch.object(base_tango.subprocess, "run", side_effect=subprocess.TimeoutExpired("powershell", 40)):
            with self.assertRaises(base_tango.BaseNoDisponible):
                base_tango.usos_lista(2, 6)


if __name__ == "__main__":
    unittest.main()
