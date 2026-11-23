"""
Lector minimo de .xls (Excel 97-2003, formato BIFF8) con la biblioteca estandar.

leer(contenido) -> {"Nombre de hoja": [[celda, ...], ...]}, igual que xlsx.leer.
Las celdas vienen como str, float, bool o None. De las formulas se toma el ultimo
resultado guardado en el archivo. Las fechas quedan como numero de serie de Excel.

Un .xls es un "archivo compuesto" OLE2 (como un mini sistema de archivos con
sectores) que adentro tiene el flujo "Workbook" con registros BIFF8.
"""

from __future__ import annotations

import struct

FIRMA_OLE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"
FIN_CADENA = 0xFFFFFFFE
LIBRE = 0xFFFFFFFF
MAX_FILAS = 100000


class XlsInvalido(ValueError):
    pass


# ------------------------------------------------------------------ OLE2
def _flujo_workbook(datos: bytes) -> bytes:
    if datos[:8] != FIRMA_OLE:
        raise XlsInvalido("El archivo no es un Excel .xls válido.")
    tam_sector = 1 << struct.unpack_from("<H", datos, 30)[0]
    tam_mini = 1 << struct.unpack_from("<H", datos, 32)[0]
    n_fat, primer_dir = struct.unpack_from("<II", datos, 44)
    corte_mini, primer_minifat, n_minifat, primer_difat, n_difat = struct.unpack_from("<IIIII", datos, 56)

    def sector(n: int) -> bytes:
        inicio = (n + 1) * tam_sector
        return datos[inicio:inicio + tam_sector]

    # Sectores de la FAT: 109 en el encabezado y el resto encadenados en la DIFAT
    sectores_fat = [x for x in struct.unpack_from("<109I", datos, 76) if x not in (FIN_CADENA, LIBRE)]
    s, vistos = primer_difat, 0
    por_sector = tam_sector // 4 - 1
    while s not in (FIN_CADENA, LIBRE) and vistos < n_difat:
        valores = struct.unpack(f"<{por_sector + 1}I", sector(s))
        sectores_fat += [x for x in valores[:por_sector] if x not in (FIN_CADENA, LIBRE)]
        s, vistos = valores[por_sector], vistos + 1
    fat = []
    for n in sectores_fat[:n_fat]:
        fat += struct.unpack(f"<{tam_sector // 4}I", sector(n))

    def cadena(inicio: int, tabla: list[int], leer) -> bytes:
        partes, n, pasos = [], inicio, 0
        while n not in (FIN_CADENA, LIBRE):
            if n >= len(tabla) or pasos > len(tabla):
                raise XlsInvalido("El archivo .xls está dañado.")
            partes.append(leer(n))
            n, pasos = tabla[n], pasos + 1
        return b"".join(partes)

    directorio = cadena(primer_dir, fat, sector)
    entradas = []
    for i in range(0, len(directorio), 128):
        e = directorio[i:i + 128]
        largo = struct.unpack_from("<H", e, 64)[0]
        nombre = e[:max(0, largo - 2)].decode("utf-16-le", "replace")
        tipo = e[66]
        inicio, tam = struct.unpack_from("<II", e, 116)
        entradas.append((nombre, tipo, inicio, tam))
    raiz = next((e for e in entradas if e[1] == 5), None)
    libro = next((e for e in entradas if e[1] == 2 and e[0] in ("Workbook", "Book")), None)
    if libro is None:
        raise XlsInvalido("El archivo .xls no tiene planillas.")
    _, _, inicio, tam = libro
    if tam >= corte_mini:
        return cadena(inicio, fat, sector)[:tam]
    # Flujo chico: va en el "mini stream" (que esta guardado en la entrada raiz)
    minifat = []
    if n_minifat:
        crudo = cadena(primer_minifat, fat, sector)
        minifat = list(struct.unpack(f"<{len(crudo) // 4}I", crudo))
    mini = cadena(raiz[2], fat, sector) if raiz else b""
    return cadena(inicio, minifat, lambda n: mini[n * tam_mini:(n + 1) * tam_mini])[:tam]


# ------------------------------------------------------------------ BIFF8
def _registros(wb: bytes, desde: int = 0):
    i = desde
    while i + 4 <= len(wb):
        tipo, largo = struct.unpack_from("<HH", wb, i)
        yield i, tipo, wb[i + 4:i + 4 + largo]
        i += 4 + largo


class _Lector:
    """Lee bytes y textos que pueden seguir en registros CONTINUE.
    Al cortarse un texto, el siguiente CONTINUE empieza con un byte que dice
    si los caracteres que siguen vienen en 1 o 2 bytes."""

    def __init__(self, partes: list[bytes]):
        self.partes, self.p, self.i = partes, 0, 0

    def _resto(self) -> int:
        return len(self.partes[self.p]) - self.i

    def bytes(self, n: int) -> bytes:
        salida = b""
        while n > 0:
            if self._resto() <= 0:
                self.p, self.i = self.p + 1, 0
                if self.p >= len(self.partes):
                    raise XlsInvalido("El archivo .xls está cortado.")
                continue
            tomo = min(n, self._resto())
            salida += self.partes[self.p][self.i:self.i + tomo]
            self.i += tomo
            n -= tomo
        return salida

    def texto(self, cch: int, ancho: bool) -> str:
        trozos = []
        while cch > 0:
            if self._resto() <= 0:
                self.p, self.i = self.p + 1, 0
                if self.p >= len(self.partes):
                    raise XlsInvalido("El archivo .xls está cortado.")
                ancho = bool(self.partes[self.p][0] & 1)
                self.i = 1
                continue
            por_char = 2 if ancho else 1
            n = min(cch, self._resto() // por_char)
            crudo = self.partes[self.p][self.i:self.i + n * por_char]
            trozos.append(crudo.decode("utf-16-le" if ancho else "latin-1"))
            self.i += n * por_char
            cch -= n
        return "".join(trozos)

    def cadena_unicode(self) -> str:
        """XLUnicodeRichExtendedString (la de la tabla de textos compartidos)."""
        cch = struct.unpack("<H", self.bytes(2))[0]
        flags = self.bytes(1)[0]
        runs = struct.unpack("<H", self.bytes(2))[0] if flags & 0x08 else 0
        ext = struct.unpack("<I", self.bytes(4))[0] if flags & 0x04 else 0
        t = self.texto(cch, bool(flags & 1))
        self.bytes(4 * runs + ext)
        return t


def _texto_corto(d: bytes, i: int, largo_2_bytes: bool) -> str:
    if largo_2_bytes:
        cch = struct.unpack_from("<H", d, i)[0]; i += 2
    else:
        cch = d[i]; i += 1
    flags = d[i]; i += 1
    if flags & 1:
        return d[i:i + 2 * cch].decode("utf-16-le", "replace")
    return d[i:i + cch].decode("latin-1")


def _rk(v: int) -> float:
    if v & 2:
        n = float(v >> 2) if v < 0x80000000 else float((v - (1 << 32)) >> 2)
    else:
        n = struct.unpack("<d", struct.pack("<Q", (v & 0xFFFFFFFC) << 32))[0]
    return n / 100 if v & 1 else n


def leer(contenido: bytes) -> dict[str, list[list]]:
    wb = _flujo_workbook(contenido)
    hojas_info, sst = [], []
    registros = list(_registros(wb))
    for k, (pos, tipo, d) in enumerate(registros):
        if tipo == 0x0085:                       # BOUNDSHEET: nombre y donde empieza la hoja
            desde, _, clase = struct.unpack_from("<IBB", d, 0)
            if clase == 0:                       # 0 = hoja de calculo (no graficos ni macros)
                hojas_info.append((_texto_corto(d, 6, False), desde))
        elif tipo == 0x00FC:                     # SST: textos compartidos (+ CONTINUE)
            partes = [d]
            for _, t2, d2 in registros[k + 1:]:
                if t2 != 0x003C:
                    break
                partes.append(d2)
            lector = _Lector(partes)
            _, unicos = struct.unpack("<II", lector.bytes(8))
            sst = [lector.cadena_unicode() for _ in range(unicos)]
        elif tipo == 0x000A and hojas_info:      # EOF del libro
            break

    hojas = {}
    for nombre, desde in hojas_info:
        celdas: dict[tuple[int, int], object] = {}
        pendiente = None                         # formula de texto: el valor viene en el registro STRING siguiente
        for _, tipo, d in _registros(wb, desde):
            if tipo == 0x000A:
                break
            if tipo in (0x00FD, 0x0203, 0x027E, 0x0204, 0x0006, 0x0205):
                fila, col = struct.unpack_from("<HH", d, 0)
                if fila > MAX_FILAS:
                    raise XlsInvalido(f"La hoja {nombre} tiene demasiadas filas.")
            if tipo == 0x00FD:                   # LABELSST
                i = struct.unpack_from("<I", d, 6)[0]
                celdas[(fila, col)] = sst[i] if i < len(sst) else ""
            elif tipo == 0x0203:                 # NUMBER
                celdas[(fila, col)] = struct.unpack_from("<d", d, 6)[0]
            elif tipo == 0x027E:                 # RK
                celdas[(fila, col)] = _rk(struct.unpack_from("<I", d, 6)[0])
            elif tipo == 0x00BD:                 # MULRK: varios RK seguidos en una fila
                fila, primera = struct.unpack_from("<HH", d, 0)
                n = (len(d) - 6) // 6
                for j in range(n):
                    celdas[(fila, primera + j)] = _rk(struct.unpack_from("<I", d, 4 + 6 * j + 2)[0])
            elif tipo == 0x0204:                 # LABEL (texto sin tabla compartida)
                celdas[(fila, col)] = _texto_corto(d, 6, True)
            elif tipo == 0x0205:                 # BOOLERR
                celdas[(fila, col)] = bool(d[6]) if d[7] == 0 else None
            elif tipo == 0x0006:                 # FORMULA: se usa el resultado guardado
                r = d[6:14]
                if r[6:8] == b"\xFF\xFF":
                    if r[0] == 0:
                        pendiente = (fila, col)
                    elif r[0] == 1:
                        celdas[(fila, col)] = bool(r[2])
                    else:
                        celdas[(fila, col)] = None if r[0] == 2 else ""
                else:
                    celdas[(fila, col)] = struct.unpack("<d", r)[0]
            elif tipo == 0x0207 and pendiente:   # STRING: resultado de texto de la formula anterior
                celdas[pendiente] = _texto_corto(d, 0, True)
                pendiente = None
        filas: list[list] = []
        if celdas:
            ultima = max(f for f, _ in celdas)
            filas = [[] for _ in range(ultima + 1)]
            for (f, c), v in sorted(celdas.items()):
                fila = filas[f]
                while len(fila) <= c:
                    fila.append(None)
                fila[c] = v
        hojas[nombre] = filas
    return hojas


def es_xls(contenido: bytes) -> bool:
    return contenido[:8] == FIRMA_OLE
