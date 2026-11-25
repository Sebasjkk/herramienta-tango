"""El modo demo arma todas las consultas con datos inventados."""

import unittest
from datetime import date

from herramienta_tango.demo import ClienteDemo
from herramienta_tango.tango import procesos
from herramienta_tango.tango.servicio import ServicioTango


class Demo(unittest.TestCase):
    def test_todas_las_consultas_traen_datos(self):
        s = ServicioTango(ClienteDemo())
        for consulta in (s.saldos_por_partida, s.articulos, s.depositos, s.clientes, s.pedidos,
                         s.listas_precios, s.precios, s.cotizaciones, s.renglones_cotizaciones, s.remitos):
            datos, _ = consulta()
            self.assertTrue(datos, consulta.__name__)
        self.assertTrue(s.ventas(date(2000, 1, 1), date.today())[0])

    def test_editar_un_precio_queda_en_memoria(self):
        c = ClienteDemo()
        r = c.obtener(procesos.PRECIOS_ABM, 1)
        c.actualizar(procesos.PRECIOS_ABM, {**r, "PRECIO": 999})
        self.assertEqual(c.obtener(procesos.PRECIOS_ABM, 1)["PRECIO"], 999)
        self.assertEqual(ClienteDemo().obtener(procesos.PRECIOS_ABM, 1)["PRECIO"], r["PRECIO"])


if __name__ == "__main__":
    unittest.main()
