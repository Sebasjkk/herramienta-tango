"""Lector de .xls y comparacion del inventario del Excel con Tango.

Los .xls de prueba se arman aca byte por byte (contenedor OLE2 + registros BIFF8),
sin librerias, para cubrir los casos delicados: textos cortados entre registros
CONTINUE, numeros RK/MULRK y formulas con resultado de texto.
"""

import struct
import time
import unittest

from herramienta_tango import inventario, xls, xlsx
from herramienta_tango.tango.modelos import Articulo, SaldoArticulo, SaldoPartida

FIN = 0xFFFFFFFE
LIBRE = 0xFFFFFFFF


def _reg(tipo: int, datos: bytes) -> bytes:
    return struct.pack("<HH", tipo, len(datos)) + datos


def _rk_entero(n: int) -> int:
    return (n << 2) | 2


def _ole(workbook: bytes) -> bytes:
    """Contenedor OLE2 con sectores de 512: FAT en el 0, directorio en el 1, el libro desde el 2."""
    workbook = workbook.ljust(max(4096, -(-len(workbook) // 512) * 512), b"\x00")
    n = len(workbook) // 512
    fat = [0xFFFFFFFD, FIN] + [3 + i for i in range(n - 1)] + [FIN]
    fat += [LIBRE] * (128 - len(fat))
    encabezado = (bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6)
                  + b"\x00" * 6 + struct.pack("<IIIIIIIII", 0, 1, 1, 0, 4096, FIN, 0, FIN, 0)
                  + struct.pack("<109I", 0, *([LIBRE] * 108)))

    def entrada(nombre: str, tipo: int, inicio: int, tam: int, hijo: int = LIBRE) -> bytes:
        n = (nombre + "\x00").encode("utf-16-le")
        return (n.ljust(64, b"\x00") + struct.pack("<HBB", len(n), tipo, 1) + struct.pack("<III", LIBRE, LIBRE, hijo)
                + b"\x00" * 36 + struct.pack("<II", inicio, tam) + b"\x00" * 4)

    # La raiz apunta al libro como "hijo" (asi lo recorren otros lectores; este lee todas las entradas)
    directorio = entrada("Root Entry", 5, FIN, 0, hijo=1) + entrada("Workbook", 2, 2, len(workbook)) + b"\x00" * 256
    return encabezado + struct.pack("<128I", *fat) + directorio + workbook


def armar_xls(hojas: dict[str, list[tuple]], textos_largos: bool = False) -> bytes:
    """hojas: {nombre: [(fila, col, valor), ...]}. valor: str, int, float o ("formula_texto", "resultado")."""
    sst: list[str] = []
    def indice(t):
        if t not in sst:
            sst.append(t)
        return sst.index(t)
    cuerpos = []
    for celdas in hojas.values():
        regs = [_reg(0x0809, struct.pack("<HHHHII", 0x600, 0x10, 0, 0, 0, 0))]
        enteros = sorted((f, c, v) for f, c, v in celdas if isinstance(v, int) and not isinstance(v, bool))
        # Los enteros de una misma fila van juntos en un MULRK (como los guarda Excel)
        por_fila: dict[int, list] = {}
        for f, c, v in enteros:
            por_fila.setdefault(f, []).append((c, v))
        for f, cs in por_fila.items():
            if len(cs) > 1 and [c for c, _ in cs] == list(range(cs[0][0], cs[0][0] + len(cs))):
                regs.append(_reg(0x00BD, struct.pack("<HH", f, cs[0][0]) + b"".join(struct.pack("<HI", 0, _rk_entero(v)) for _, v in cs)
                                 + struct.pack("<H", cs[-1][0])))
            else:
                for c, v in cs:
                    regs.append(_reg(0x027E, struct.pack("<HHHI", f, c, 0, _rk_entero(v))))
        for f, c, v in celdas:
            if isinstance(v, str):
                regs.append(_reg(0x00FD, struct.pack("<HHHI", f, c, 0, indice(v))))
            elif isinstance(v, float):
                regs.append(_reg(0x0203, struct.pack("<HHHd", f, c, 0, v)))
            elif isinstance(v, tuple):
                regs.append(_reg(0x0006, struct.pack("<HHH", f, c, 0) + bytes([0, 0, 0, 0, 0, 0, 0xFF, 0xFF]) + b"\x00" * 6))
                t = v[1].encode("latin-1")
                regs.append(_reg(0x0207, struct.pack("<HB", len(t), 0) + t))
        regs.append(_reg(0x000A, b""))
        cuerpos.append(b"".join(regs))

    # Tabla de textos; con textos_largos el ultimo se corta: sigue en un CONTINUE y pasa a UTF-16
    partes = [struct.pack("<II", len(sst), len(sst))]
    continuacion = b""
    for k, t in enumerate(sst):
        if textos_largos and k == len(sst) - 1 and len(t) > 4:
            a, b = t[:4], t[4:]
            partes.append(struct.pack("<HB", len(t), 0) + a.encode("latin-1"))
            continuacion = b"\x01" + b.encode("utf-16-le")
        elif all(ord(ch) < 256 for ch in t):
            partes.append(struct.pack("<HB", len(t), 0) + t.encode("latin-1"))
        else:
            partes.append(struct.pack("<HB", len(t), 1) + t.encode("utf-16-le"))
    sst_regs = _reg(0x00FC, b"".join(partes)) + (_reg(0x003C, continuacion) if continuacion else b"")

    def globales(desplazamientos):
        hs = b"".join(_reg(0x0085, struct.pack("<IBBBB", d, 0, 0, len(n), 0) + n.encode("latin-1"))
                      for d, n in zip(desplazamientos, hojas))
        return _reg(0x0809, struct.pack("<HHHHII", 0x600, 5, 0, 0, 0, 0)) + hs + sst_regs + _reg(0x000A, b"")
    base = len(globales([0] * len(hojas)))
    desplazamientos, d = [], base
    for c in cuerpos:
        desplazamientos.append(d)
        d += len(c)
    return _ole(globales(desplazamientos) + b"".join(cuerpos))


INVENTARIO = {
    "Inv. Polvo": [(0, 0, "Tipo"), (0, 1, "Cantidad"), (0, 2, "Unidad"), (0, 3, "SAP"), (0, 4, "Descripcion"), (0, 8, "KG"),
                   (1, 0, "Polvo"), (1, 1, 55), (1, 2, "Lbs"), (1, 3, 1000125), (1, 4, " METCO 130"), (1, 8, 55 * 0.45359237),
                   (2, 0, "Polvo"), (2, 1, 10.5), (2, 2, "kg"), (2, 3, 1000300), (2, 4, "METCO 443 NS"),
                   (3, 0, "Polvo"), (3, 1, 3), (3, 2, "latas"), (3, 3, 1000500), (3, 4, "LATA RARA"),
                   (4, 0, ("formula", "Polvo")), (4, 1, 6), (4, 2, "kg"), (4, 3, 1000999), (4, 4, "SOLO EN EXCEL")],
    "Inv. Repuesto": [(0, 0, "Tipo"), (0, 1, "Cantidad"), (0, 2, "SAP"), (0, 3, "Descripcion"),
                      (1, 0, "Repuesto"), (1, 1, 6), (1, 2, "0039812"), (1, 3, "BELT 1250X50"),
                      (2, 0, "Repuesto"), (2, 1, 1), (2, 3, "DJ1182")],
    "Obsoletos": [(0, 0, "SAP"), (1, 0, 1000777)],
}


class TestLectorXls(unittest.TestCase):
    def test_lee_celdas(self):
        h = xls.leer(armar_xls(INVENTARIO))
        self.assertEqual(list(h), ["Inv. Polvo", "Inv. Repuesto", "Obsoletos"])
        p = h["Inv. Polvo"]
        self.assertEqual(p[0][:5], ["Tipo", "Cantidad", "Unidad", "SAP", "Descripcion"])
        self.assertEqual((p[1][1], p[1][3], p[2][1]), (55.0, 1000125.0, 10.5))     # RK enteros y NUMBER
        self.assertEqual(p[4][0], "Polvo")                                          # formula con resultado de texto
        self.assertEqual(h["Inv. Repuesto"][1][2], "0039812")

    def test_texto_cortado_entre_registros(self):
        h = xls.leer(armar_xls({"Hoja": [(0, 0, "corto"), (0, 1, "ÑANDÚ cortado al medio €")]}, textos_largos=True))
        self.assertEqual(h["Hoja"][0], ["corto", "ÑANDÚ cortado al medio €"])

    def test_no_es_xls(self):
        with self.assertRaises(xls.XlsInvalido):
            xls.leer(b"esto no es un excel")
        self.assertFalse(xls.es_xls(b"PK\x03\x04"))


class Servicio:
    def articulos(self, forzar=False):
        a = lambda cod, d, u, part=True: Articulo(None, cod, d, "", "", "", part, True, "", u, "", 0, 0, 0)
        return [a("01000125", "METCO 130", "KG"), a("1000300", "METCO 443", "KG"), a("1000500", "LATAS", "KG"),
                a("0039812", "BELT", "UNI", part=False), a("1000777", "VIEJO", "KG"), a("ZINC9", "ZINC FANTASMA", "KG")], time.time()

    def saldos_por_partida(self, forzar=False):
        s = lambda cod, dep, v: SaldoPartida(None, cod, "", dep, "P1", "", None, "KG", v)
        return [s("01000125", "CENTRAL", 24.95), s("1000300", "CENTRAL", 8.5), s("1000300", "INTA-CICV", 2),
                s("1000777", "CENTRAL", 3), s("ZINC9", "CENTRAL", 5000)], time.time()

    def saldos_por_articulo(self, forzar=False):
        return [SaldoArticulo(None, "0039812", "BELT", "CENTRAL", "UNI", 6, 0, 0)], time.time()


class TestComparacion(unittest.TestCase):
    def test_compara_con_tango(self):
        r = inventario.comparar(armar_xls(INVENTARIO), Servicio(), "Inventario_prueba.xls")
        f = {x["codigo_tango"] or x["codigo_excel"] or x["descripcion_excel"]: x for x in r["filas"]}
        # 55 lbs = 24,95 kg y el codigo de Tango tiene un cero adelante: coincide
        self.assertEqual((f["01000125"]["estado"], f["01000125"]["codigo_excel"]), ("Coincide", "1000125"))
        # 10,5 kg en el Excel, 8,5 en Central (y 2 en otro deposito, que no entran en la diferencia)
        self.assertEqual((f["1000300"]["estado"], f["1000300"]["diferencia"]), ("Tango tiene menos", -2.0))
        self.assertIn("Inta-Cicv 2", f["1000300"]["tango_otros_depositos"])
        self.assertEqual(f["1000500"]["estado"], "Revisar unidad")                 # latas contra kg
        self.assertEqual(f["0039812"]["estado"], "Coincide")                       # sin partidas: saldo por articulo
        self.assertEqual(f["1000999"]["estado"], "No está en Tango")
        self.assertEqual(f["DJ1182"]["estado"], "No está en Tango")                # sin codigo: se busco por descripcion
        self.assertEqual((f["ZINC9"]["estado"], f["ZINC9"]["diferencia"]), ("Solo en Tango", 5000))
        self.assertIn("Obsoletos", f["1000777"]["notas"])                          # solo en Tango, pero figura en Obsoletos
        hojas = xlsx.leer(r["archivo"])
        self.assertEqual(list(hojas)[:3], ["Resumen", "Diferencias", "Revisar unidad"])
        self.assertEqual(len(hojas["Todo"]) - 1, len(r["filas"]))

    def test_sin_hojas_de_inventario(self):
        with self.assertRaises(inventario.InventarioInvalido):
            inventario.comparar(armar_xls({"Ingresos": [(0, 0, "x")]}), Servicio())


if __name__ == "__main__":
    unittest.main()
