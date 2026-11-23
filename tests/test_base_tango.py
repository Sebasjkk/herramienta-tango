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

    def test_comprobantes(self):
        js = ('{"filas":[{"T_COMP":"FAC","N_COMP":"A000100001234","FECHA_EMIS":"2007-03-01","COD_CLIENT":"METALI",'
              '"RAZON_CLIENTE":"METALIZA S.A.","IMPORTE":1500.5,"MON_CTE":true,"OTRA":1}]}')
        with mock.patch.object(base_tango.subprocess, "run", return_value=salida(js)) as run:
            cs = base_tango.comprobantes_lista(6, 2007)
        self.assertEqual(cs[0]["tipo"], "Factura")
        self.assertEqual(cs[0]["numero"], "A 0001-00001234")
        self.assertEqual(cs[0]["importe"], 1500.5)
        self.assertIn("NRO_DE_LIS = 6 AND YEAR(f.FECHA_EMIS) = 2007", run.call_args[0][0][-1])

    def test_renglones_validan_el_comprobante(self):
        for t, n in (("FAC", "A0001' OR 1=1"), ("FACTURA", "A000100001234"), ("", "")):
            with self.assertRaises(ValueError):
                base_tango.renglones_comprobante(t, n)
        js = '{"filas":[{"N_RENGL_V":2,"COD_ARTICU":"B","CANTIDAD":1},{"N_RENGL_V":1,"COD_ARTICU":"A","CANTIDAD":3,"PRECIO_NET":10,"DESC_ARTICULO":"Zinc"}]}'
        with mock.patch.object(base_tango.subprocess, "run", return_value=salida(js)) as run:
            rs = base_tango.renglones_comprobante("fac", "A000100001234")
        self.assertEqual([r["codigo"] for r in rs], ["A", "B"])
        self.assertEqual(rs[0]["descripcion"], "Zinc")
        self.assertIn("T_COMP = 'FAC' AND r.N_COMP = 'A000100001234'", run.call_args[0][0][-1])


    def test_movimientos(self):
        js = ('{"consulta":1,"filas":[{"C_T_COMP":"REM","C_N_COMP":"R000800000110","C_FECHA":"2026-11-14","C_CLIENTE":"METALIZA S.A.",'
              '"TIPO_MOV":"S","CANTIDAD":25,"COD_DEPOSI":" 1","N_PARTIDA":"HIST-PO0001"},'
              '{"C_T_COMP":"AJU","C_N_COMP":" 000100000012","C_FECHA":"2026-11-10","TIPO_MOV":"E","CANTIDAD":55.5}]}')
        with mock.patch.object(base_tango.subprocess, "run", return_value=salida(js)) as run:
            ms = base_tango.movimientos_articulo(" 01029071 ")
        script = run.call_args[0][0][-1]
        self.assertIn("r.COD_ARTICU = '01029071'", script)
        self.assertNotIn("UPDATE", script.upper())
        self.assertEqual((ms[0]["tipo"], ms[0]["cantidad"], ms[0]["tercero"], ms[0]["partida"], ms[0]["deposito"]),
                         ("Remito", -25, "METALIZA S.A.", "HIST-PO0001", "1"))
        self.assertEqual((ms[1]["tipo"], ms[1]["cantidad"], ms[1]["entrada"]), ("Ajuste", 55.5, True))

    def test_movimientos_codigo_invalido(self):
        for malo in ("X'; DROP TABLE STA11 --", "", "A" * 30, "$(calc)"):
            with self.assertRaises(ValueError):
                base_tango.movimientos_articulo(malo)


    def test_remitos_de_un_pedido(self):
        js = ('{"columnas":["STA20.NRO_PEDIDO"],"relacion":true,"filas":['
              '{"T_COMP":"REM","N_COMP":"R000800000110","FECHA":"2026-11-14","COD_ARTICU":"ZINC","CANTIDAD":50,"TIPO_MOV":"S"},'
              '{"T_COMP":"REM","N_COMP":"R000800000110","FECHA":"2026-11-14","COD_ARTICU":"METCO","CANTIDAD":5,"TIPO_MOV":"S"},'
              '{"T_COMP":"DEV","N_COMP":"R000800000115","FECHA":"2026-11-18","COD_ARTICU":"ZINC","CANTIDAD":2,"TIPO_MOV":"E"}]}')
        with mock.patch.object(base_tango.subprocess, "run", return_value=salida(js)) as run:
            r = base_tango.remitos_pedido("31")
        self.assertIn("WHERE ID_GVA21 = 31", run.call_args[0][0][-1])
        self.assertTrue(r["relacion"])
        self.assertEqual([(c["tipo"], c["numero"], len(c["renglones"])) for c in r["comprobantes"]],
                         [("Remito", "R 0008-00000110", 2), ("Devolución", "R 0008-00000115", 1)])
        self.assertEqual(r["comprobantes"][1]["renglones"][0]["cantidad"], -2)       # la devolucion resta
        with self.assertRaises(ValueError):
            base_tango.remitos_pedido("31; DROP TABLE GVA21")

    def test_remitos_sin_relacion(self):
        js = '{"columnas":"STA14.COD_PEDIDO_X","relacion":false,"filas":[]}'
        with mock.patch.object(base_tango.subprocess, "run", return_value=salida(js)):
            r = base_tango.remitos_pedido(31)
        self.assertEqual((r["relacion"], r["comprobantes"], r["columnas"]), (False, [], ["STA14.COD_PEDIDO_X"]))


class TestDesdeOtraPC(unittest.TestCase):
    def setUp(self):
        base_tango._cache.clear()

    def test_reconoce_el_servidor(self):
        with mock.patch.object(base_tango, "_servidor_tango", return_value=("desktop-b11ba4h", 8085)):
            with mock.patch.object(base_tango.socket, "gethostname", return_value="DESKTOP-B11BA4H"):
                self.assertTrue(base_tango.es_servidor())
            with mock.patch.object(base_tango.socket, "gethostname", return_value="SC"):
                self.assertFalse(base_tango.es_servidor())

    def test_otra_pc_le_pide_al_servidor(self):
        import io, json
        resp = io.BytesIO(json.dumps({"ok": True, "datos": {"cotizaciones": [], "facturas_por_anio": []}}).encode())
        with mock.patch.object(base_tango, "es_servidor", return_value=False), \
             mock.patch.object(base_tango, "_servidor_tango", return_value=("desktop-b11ba4h", 8085)), \
             mock.patch.object(base_tango.urllib.request, "urlopen", return_value=resp) as u, \
             mock.patch.object(base_tango, "_correr") as local:
            d = base_tango.usos_lista(2, 6)
        local.assert_not_called()
        self.assertEqual(u.call_args[0][0], "http://desktop-b11ba4h:8085/api/base/usos?id=2&nro=6")
        self.assertEqual(d["cotizaciones"], [])

    def test_error_del_servidor_se_muestra(self):
        import io, json
        resp = io.BytesIO(json.dumps({"ok": False, "error": "sin permiso"}).encode())
        with mock.patch.object(base_tango, "es_servidor", return_value=False), \
             mock.patch.object(base_tango, "_servidor_tango", return_value=("srv", 8085)), \
             mock.patch.object(base_tango.urllib.request, "urlopen", return_value=resp):
            with self.assertRaisesRegex(base_tango.BaseNoDisponible, "sin permiso"):
                base_tango.comprobantes_lista(6, 2007)

    def test_servidor_responde_siempre_local(self):
        with mock.patch.object(base_tango, "_usos_local", return_value={"x": 1}) as loc:
            self.assertEqual(base_tango.responder_remoto("usos", {"id": ["2"], "nro": ["6"]}), {"x": 1})
        loc.assert_called_once_with(2, 6)
        with self.assertRaises(ValueError):
            base_tango.responder_remoto("borrar", {})


if __name__ == "__main__":
    unittest.main()
