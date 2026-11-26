"""
Lecturas puntuales de la base SQL de Tango, para lo que la API no informa.

Solo lectura y solo consultas fijas: la API no dice con que lista de precios se
hizo cada cotizacion o factura (probado el 20/11/2026), y la base si
(GVA08.ID_GVA10, GVA12.NRO_DE_LIS). Corre en el servidor, donde esta la
Herramienta, con PowerShell y System.Data.SqlClient (Python no trae driver de
SQL Server). Nunca se escribe en la base.

La cuenta con la que corre la Herramienta (SYSTEM en modo servidor) necesita
permiso de lectura en la base; si no lo tiene, se devuelve el motivo.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import os
import queue
import re
import subprocess
import sys
import threading
import time

SERVIDOR_SQL = os.environ.get("HERRAMIENTA_TANGO_SQL", "")       # vacio: se prueba solo (ver _FUNCION)
INSTANCIA = os.environ.get("HERRAMIENTA_TANGO_INSTANCIA", "AXSQLEXPRESS")
BASE = os.environ.get("HERRAMIENTA_TANGO_BASE", "SIANCO_SA")
VIGENCIA = 300
_cache: dict[tuple, tuple[float, dict]] = {}


class BaseNoDisponible(Exception):
    pass


_FUNCION = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$inst = '__INSTANCIA__'
$cands = New-Object System.Collections.Generic.List[string]
if ('__SERVIDOR__') { $cands.Add('__SERVIDOR__') }
$cands.Add("lpc:$env:COMPUTERNAME\$inst")
$cands.Add("$env:COMPUTERNAME\$inst")
$cands.Add("localhost\$inst")
try {
  $k = Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server' -ErrorAction Stop |
       Where-Object { $_.PSChildName -like "MSSQL*.$inst" } | Select-Object -First 1
  if ($k) { $t = Get-ItemProperty (Join-Path $k.PSPath 'MSSQLServer\SuperSocketNetLib\Tcp\IPAll')
    $port = if ($t.TcpPort) { $t.TcpPort } else { $t.TcpDynamicPorts }
    if ($port) { $cands.Add("tcp:127.0.0.1,$port") } }
} catch {}
$cs = $null; $errores = @()
foreach ($srv in $cands) {
  $prueba = "Server=$srv;Database=__BASE__;Integrated Security=True;Connect Timeout=5;ApplicationIntent=ReadOnly"
  try { $cn = New-Object System.Data.SqlClient.SqlConnection($prueba); $cn.Open(); $cn.Close(); $cs = $prueba; break }
  catch { $m = if ($_.Exception.InnerException) { $_.Exception.InnerException.Message } else { $_.Exception.Message }
          $m = ($m -replace '\s+', ' '); if ($m.Length -gt 160) { $m = $m.Substring(0, 160) + '...' }
          $errores += "$srv -> $m" }
}
if (-not $cs) { [Console]::Error.WriteLine(($errores -join ' | ')); exit 3 }
function Q($sql) {
  $t = New-Object System.Data.DataTable
  $a = New-Object System.Data.SqlClient.SqlDataAdapter($sql, $cs)
  [void]$a.Fill($t)
  ,@($t.Rows | ForEach-Object { $r = $_; $o = [ordered]@{}
      foreach ($c in $t.Columns) { $v = $r[$c.ColumnName]
        if ($v -is [DBNull] -or $v -is [byte[]]) { $v = $null } elseif ($v -is [datetime]) { $v = $v.ToString('yyyy-MM-dd') } elseif ($v -is [string]) { $v = $v.Trim() }
        $o[$c.ColumnName] = $v }
      [pscustomobject]$o })
}
"""

_USOS_LISTA = r"""
$out = [ordered]@{}
$out.cotizaciones = Q "SELECT TOP 50 q.ID_GVA08 AS id, q.N_COTIZ AS numero, q.FECHA_EMIS AS fecha, q.FECHA_VIG AS vigencia, q.ESTADO AS estado, q.COD_CLIENT AS codigo_cliente, c.RAZON_SOCI AS cliente FROM GVA08 q LEFT JOIN GVA14 c ON c.ID_GVA14 = q.ID_GVA14 WHERE q.ID_GVA10 = __ID__ ORDER BY q.FECHA_EMIS DESC"
$out.cotizaciones_total = (Q "SELECT COUNT(*) AS n FROM GVA08 WHERE ID_GVA10 = __ID__")[0].n
$out.facturas_por_anio = Q "SELECT YEAR(FECHA_EMIS) AS anio, COUNT(*) AS n FROM GVA12 WHERE NRO_DE_LIS = __NRO__ GROUP BY YEAR(FECHA_EMIS) ORDER BY 1"
$out | ConvertTo-Json -Depth 4 -Compress
"""


# PowerShell que queda abierto y recibe las consultas una por una: arrancar
# PowerShell y encontrar el SQL Server cuesta un par de segundos, asi se paga
# una sola vez. Si algo falla con el, se usa el camino de siempre (un
# PowerShell por consulta), que ademas da el mensaje de error detallado.
_BUCLE = r"""
[Console]::InputEncoding = [Text.Encoding]::UTF8
[Console]::Out.WriteLine('###LISTO###'); [Console]::Out.Flush()
while ($true) {
  $lineas = New-Object System.Collections.Generic.List[string]
  while ($true) { $l = [Console]::In.ReadLine(); if ($l -eq $null) { exit 0 }; if ($l -eq '###FIN###') { break }; $lineas.Add($l) }
  try { $r = (& ([scriptblock]::Create($lineas -join "`n"))) -join ''
        [Console]::Out.WriteLine('###OK###' + $r) }
  catch { [Console]::Out.WriteLine('###ERR###' + ($_.Exception.Message -replace '\s+', ' ')) }
  [Console]::Out.Flush()
}
"""


class _Trabajador:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._salida = None
        self._lock = threading.Lock()

    def _cerrar(self) -> None:
        if self._proc:
            try:
                self._proc.kill()
            except OSError:
                pass
        self._proc = None

    def _linea(self, tiempo: float) -> str | None:
        try:
            return self._salida.get(timeout=tiempo)
        except queue.Empty:
            return None

    def _arrancar(self) -> bool:
        completo = (_FUNCION.replace("__SERVIDOR__", SERVIDOR_SQL).replace("__INSTANCIA__", INSTANCIA)
                    .replace("__BASE__", BASE) + _BUCLE)
        self._proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", completo],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._salida = queue.Queue()
        proc, salida = self._proc, self._salida

        def leer():
            for l in proc.stdout:
                salida.put(l.rstrip("\r\n"))
            salida.put(None)
        threading.Thread(target=leer, name="base-tango", daemon=True).start()
        while True:
            l = self._linea(60)
            if l is None:
                self._cerrar()
                return False
            if l == "###LISTO###":
                return True

    def correr(self, script: str, tiempo: int) -> dict | None:
        """El resultado, o None si el trabajador no pudo o esta ocupado (se usa el camino de siempre)."""
        if not self._lock.acquire(blocking=False):
            return None                 # otra consulta en curso: esta va por separado, sin esperar
        try:
            try:
                if (self._proc is None or self._proc.poll() is not None) and not self._arrancar():
                    return None
                self._proc.stdin.write(script.strip() + "\n###FIN###\n")
                self._proc.stdin.flush()
                while True:
                    l = self._linea(tiempo)
                    if l is None:
                        self._cerrar()
                        return None
                    if l.startswith("###OK###"):
                        return json.loads(l[8:].strip().splitlines()[-1])
                    if l.startswith("###ERR###"):
                        return None
            except (OSError, ValueError):
                self._cerrar()
                return None
        finally:
            self._lock.release()


_trabajador = _Trabajador()


def _correr(script: str, tiempo: int = 60) -> dict:
    if os.environ.get("HERRAMIENTA_TANGO_DEMO") == "1":
        raise BaseNoDisponible("En el modo demo no hay base de datos de Tango.")
    if sys.platform != "win32":
        raise BaseNoDisponible("La base de Tango solo se lee desde el servidor (Windows).")
    if os.environ.get("HERRAMIENTA_TANGO_SQL_SIMPLE") != "1":
        datos = _trabajador.correr(script, tiempo)
        if datos is not None:
            return datos
    return _correr_aparte(script, tiempo)


def _correr_aparte(script: str, tiempo: int = 60) -> dict:
    if sys.platform != "win32":
        raise BaseNoDisponible("La base de Tango solo se lee desde el servidor (Windows).")
    completo = (_FUNCION.replace("__SERVIDOR__", SERVIDOR_SQL).replace("__INSTANCIA__", INSTANCIA)
                .replace("__BASE__", BASE) + script)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", completo],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=tiempo,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BaseNoDisponible(f"No se pudo consultar la base de Tango: {e}") from None
    if r.returncode != 0 or not r.stdout.strip():
        detalle = " ".join((r.stderr or r.stdout or "").split())[:900]
        if any(t in detalle for t in ("Login failed", "Error de inicio de sesi", "Cannot open database", "No se puede abrir la base")):
            raise BaseNoDisponible("La Herramienta no tiene permiso para leer la base de Tango. " + detalle)
        raise BaseNoDisponible(f"No se pudo consultar la base de Tango: {detalle or 'sin respuesta'}")
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        raise BaseNoDisponible("La base de Tango devolvió algo que no se pudo leer.") from None


def _usos_local(id_lista: int, numero_lista: int) -> dict:
    """Cotizaciones (GVA08) y facturas (GVA12, por año) que usan la lista."""
    id_lista, numero_lista = int(id_lista), int(numero_lista)     # enteros: nada de texto libre en el SQL
    clave = ("usos", id_lista, numero_lista)
    if clave in _cache and time.time() - _cache[clave][0] < VIGENCIA:
        return _cache[clave][1]
    datos = _correr(_USOS_LISTA.replace("__ID__", str(id_lista)).replace("__NRO__", str(numero_lista)))
    for campo in ("cotizaciones", "facturas_por_anio"):
        v = datos.get(campo)
        datos[campo] = [] if v is None else (v if isinstance(v, list) else [v])
    _cache[clave] = (time.time(), datos)
    return datos


_COMPROBANTES = r"""
$out = [ordered]@{}
$out.filas = Q "SELECT TOP 500 f.*, c.RAZON_SOCI AS RAZON_CLIENTE FROM GVA12 f LEFT JOIN GVA14 c ON c.COD_CLIENT = f.COD_CLIENT WHERE f.NRO_DE_LIS = __NRO__ AND YEAR(f.FECHA_EMIS) = __ANIO__ ORDER BY f.FECHA_EMIS, f.N_COMP"
$out | ConvertTo-Json -Depth 4 -Compress
"""

_RENGLONES = r"""
$out = [ordered]@{}
$out.filas = Q "SELECT r.*, a.DESCRIPCIO AS DESC_ARTICULO FROM GVA53 r LEFT JOIN STA11 a ON a.COD_ARTICU = r.COD_ARTICU WHERE r.T_COMP = '__TCOMP__' AND r.N_COMP = '__NCOMP__'"
$out | ConvertTo-Json -Depth 4 -Compress
"""

_TIPOS = {"FAC": "Factura", "N/C": "Nota de crédito", "N/D": "Nota de débito", "REM": "Remito", "REC": "Recibo",
          "AJU": "Ajuste", "PED": "Pedido", "TIN": "Toma de inventario", "TRA": "Transferencia", "TRF": "Transferencia",
          "DEV": "Devolución", "EGR": "Egreso", "ING": "Ingreso", "RCP": "Recepción", "RCO": "Remito de compra",
          "DES": "Despacho", "IMP": "Importación"}


def _filas(datos: dict) -> list[dict]:
    v = datos.get("filas")
    return [] if v is None else (v if isinstance(v, list) else [v])


def _campo(fila: dict, *nombres, defecto=None):
    for n in nombres:
        if fila.get(n) not in (None, ""):
            return fila[n]
    return defecto


def _numero_comprobante(n: str) -> str:
    """'A000100001234' -> 'A 0001-00001234' (como lo muestra Tango)."""
    n = (n or "").strip()
    m = re.fullmatch(r"([A-Z]?)\s*(\d{4,5})(\d{8})", n)
    return f"{m.group(1)} {m.group(2)[-4:]}-{m.group(3)}".strip() if m else n


def _comprobantes_local(numero_lista: int, anio: int) -> list[dict]:
    """Comprobantes de venta (GVA12) de un año hechos con la lista."""
    numero_lista, anio = int(numero_lista), int(anio)
    clave = ("comprobantes", numero_lista, anio)
    if clave in _cache and time.time() - _cache[clave][0] < VIGENCIA:
        return _cache[clave][1]
    filas = _filas(_correr(_COMPROBANTES.replace("__NRO__", str(numero_lista)).replace("__ANIO__", str(anio))))
    res = []
    for f in filas:
        t = str(f.get("T_COMP") or "").strip()
        res.append({"t_comp": t, "tipo": _TIPOS.get(t, t), "n_comp": str(f.get("N_COMP") or "").rstrip(),   # tal cual (puede empezar con espacio)
                    "numero": _numero_comprobante(str(f.get("N_COMP") or "")), "fecha": f.get("FECHA_EMIS"),
                    "codigo_cliente": str(f.get("COD_CLIENT") or "").strip(), "cliente": f.get("RAZON_CLIENTE") or "",
                    "importe": _campo(f, "IMPORTE", "IMPORTE_TOTAL"), "moneda": "U$S" if f.get("MON_CTE") is False else "$"})
    _cache[clave] = (time.time(), res)
    return res


_T_COMP = re.compile(r"[A-Z/]{1,3}")
_N_COMP = re.compile(r"[A-Z0-9 ]{1,14}")


def _renglones_validar(t_comp: str, n_comp: str) -> tuple[str, str]:
    t_comp, n_comp = (t_comp or "").strip().upper(), (n_comp or "").rstrip().upper()
    if not _T_COMP.fullmatch(t_comp) or not _N_COMP.fullmatch(n_comp):
        raise ValueError("Comprobante inválido.")
    return t_comp, n_comp


def _renglones_local(t_comp: str, n_comp: str) -> list[dict]:
    """Renglones (GVA53) de un comprobante. Los textos se validan antes de ir al SQL."""
    t_comp, n_comp = _renglones_validar(t_comp, n_comp)
    clave = ("renglones", t_comp, n_comp)
    if clave in _cache and time.time() - _cache[clave][0] < VIGENCIA:
        return _cache[clave][1]
    filas = _filas(_correr(_RENGLONES.replace("__TCOMP__", t_comp).replace("__NCOMP__", n_comp)))
    filas.sort(key=lambda f: _campo(f, "N_RENGL_V", "RENGLON", defecto=0) or 0)
    res = [{"codigo": str(f.get("COD_ARTICU") or "").strip(), "descripcion": f.get("DESC_ARTICULO") or "",
            "cantidad": _campo(f, "CANTIDAD", "CANT_FACT", defecto=0),
            "precio": _campo(f, "PRECIO_NET", "PRECIO", "PRECIO_PAN")} for f in filas]
    _cache[clave] = (time.time(), res)
    return res



# ------------------------------------------------------------------ movimientos de un articulo
# STA14: cabecera del movimiento de stock (comprobante, fecha, cliente o proveedor)
# STA20: renglones (articulo, cantidad, deposito, E/S)
# La forma de unirlas cambio entre versiones de Tango (ID_STA14 o TCOMP_IN_S + NCOMP_IN_S) y no
# todas las bases tienen los mismos nombres de columna: se prueba de la consulta mas completa a la
# mas simple y se usa la primera que funcione. Todas son SELECT: nunca se escribe.
_MOVIMIENTOS = r"""
$out = [ordered]@{}
$consultas = @(
  "SELECT TOP __N__ c.T_COMP AS C_T_COMP, c.N_COMP AS C_N_COMP, c.FECHA_MOV AS C_FECHA, c.COD_PRO_CL AS C_COD, g.RAZON_SOCI AS C_CLIENTE, p.NOM_PROVEE AS C_PROVEEDOR, d.NOMBRE_SUC AS C_DEPOSITO, r.* FROM STA20 r JOIN STA14 c ON c.ID_STA14 = r.ID_STA14 LEFT JOIN GVA14 g ON g.COD_CLIENT = c.COD_PRO_CL LEFT JOIN CPA01 p ON p.COD_PROVEE = c.COD_PRO_CL LEFT JOIN STA22 d ON d.COD_SUCURS = r.COD_DEPOSI WHERE r.COD_ARTICU = '__COD__' ORDER BY c.FECHA_MOV DESC, c.ID_STA14 DESC",
  "SELECT TOP __N__ c.T_COMP AS C_T_COMP, c.N_COMP AS C_N_COMP, c.FECHA_MOV AS C_FECHA, c.COD_PRO_CL AS C_COD, g.RAZON_SOCI AS C_CLIENTE, r.* FROM STA20 r JOIN STA14 c ON c.ID_STA14 = r.ID_STA14 LEFT JOIN GVA14 g ON g.COD_CLIENT = c.COD_PRO_CL WHERE r.COD_ARTICU = '__COD__' ORDER BY c.FECHA_MOV DESC, c.ID_STA14 DESC",
  "SELECT TOP __N__ c.T_COMP AS C_T_COMP, c.N_COMP AS C_N_COMP, c.FECHA_MOV AS C_FECHA, c.COD_PRO_CL AS C_COD, r.* FROM STA20 r JOIN STA14 c ON c.TCOMP_IN_S = r.TCOMP_IN_S AND c.NCOMP_IN_S = r.NCOMP_IN_S WHERE r.COD_ARTICU = '__COD__' ORDER BY c.FECHA_MOV DESC",
  "SELECT TOP __N__ r.* FROM STA20 r WHERE r.COD_ARTICU = '__COD__' ORDER BY r.FECHA_MOV DESC"
)
$ultimo = ''
foreach ($sql in $consultas) {
  try { $out.filas = Q $sql; $out.consulta = [array]::IndexOf($consultas, $sql); break }
  catch { $ultimo = $_.Exception.Message }
}
if (-not $out.Contains('consulta')) { [Console]::Error.WriteLine("Movimientos: $ultimo"); exit 4 }
$out | ConvertTo-Json -Depth 4 -Compress
"""
MAX_MOVIMIENTOS = 60
_COD_ARTICULO = re.compile(r"[A-Za-z0-9 ._/\-]{1,20}")


def _validar_articulo(codigo: str) -> str:
    codigo = (codigo or "").strip()
    if not _COD_ARTICULO.fullmatch(codigo):
        raise ValueError("Código de artículo inválido.")
    return codigo


def _movimientos_local(codigo: str) -> list[dict]:
    """Ultimos movimientos de stock de un articulo, del mas nuevo al mas viejo."""
    codigo = _validar_articulo(codigo)
    clave = ("movimientos", codigo)
    if clave in _cache and time.time() - _cache[clave][0] < VIGENCIA:
        return _cache[clave][1]
    filas = _filas(_correr(_MOVIMIENTOS.replace("__COD__", codigo).replace("__N__", str(MAX_MOVIMIENTOS))))
    res = []
    for f in filas:
        t = str(_campo(f, "C_T_COMP", "T_COMP", defecto="")).strip()
        tipo_mov = str(f.get("TIPO_MOV") or "").strip().upper()
        cantidad = _campo(f, "CANTIDAD", "CANT_STOCK", defecto=0) or 0
        try:
            cantidad = float(cantidad)
        except (TypeError, ValueError):
            cantidad = 0.0
        partida = next((str(v).strip() for k, v in f.items() if "PARTIDA" in k.upper() and v not in (None, "")), "")
        res.append({
            "fecha": _campo(f, "C_FECHA", "FECHA_MOV"),
            "t_comp": t, "tipo": _TIPOS.get(t, t),
            "numero": _numero_comprobante(str(_campo(f, "C_N_COMP", "N_COMP", defecto=""))),
            "entrada": tipo_mov != "S",
            "cantidad": round(abs(cantidad), 4) * (-1 if tipo_mov == "S" else 1),
            "deposito": str(_campo(f, "C_DEPOSITO", "COD_DEPOSI", defecto="")).strip(),
            "tercero": str(_campo(f, "C_CLIENTE", "C_PROVEEDOR", "C_COD", defecto="")).strip(),
            "partida": partida,
        })
    _cache[clave] = (time.time(), res)
    return res


# ------------------------------------------------------------------ remitos de un pedido
# El pedido (GVA21) guarda solo el ultimo remito. Para ver todas las entregas hay que buscar
# los renglones de stock (STA20) o las cabeceras (STA14) que apuntan al pedido. El nombre de esa
# columna cambia entre versiones de Tango: se mira cuales existen y se usa la primera que este.
# El numero del pedido se toma de GVA21 dentro del mismo SQL (por su ID, que es un entero).
_REMITOS_PEDIDO = r"""
$out = [ordered]@{}
$cols = Q "SELECT TABLE_NAME AS t, COLUMN_NAME AS c FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME IN ('STA14','STA20') AND (COLUMN_NAME LIKE '%PEDI%' OR COLUMN_NAME LIKE '%GVA21%')"
$out.columnas = @($cols | ForEach-Object { "$($_.t).$($_.c)" })
# GVA106: cuanto de cada renglon del pedido salio en cada remito (encontrado el 26/11/2026)
try {
  $out.filas = Q "SELECT c.T_COMP AS T_COMP, c.N_COMP AS N_COMP, c.FECHA_MOV AS FECHA, d.COD_ARTICU AS COD_ARTICU, g.CANT_REM AS CANTIDAD, 'S' AS TIPO_MOV FROM GVA106 g JOIN GVA21 p ON p.NRO_PEDIDO COLLATE DATABASE_DEFAULT = g.NRO_PEDIDO COLLATE DATABASE_DEFAULT AND p.TALON_PED = g.TALON_PED JOIN STA14 c ON c.TCOMP_IN_S COLLATE DATABASE_DEFAULT = g.TCOMP_IN_S COLLATE DATABASE_DEFAULT AND c.NCOMP_IN_S COLLATE DATABASE_DEFAULT = g.NCOMP_IN_S COLLATE DATABASE_DEFAULT LEFT JOIN GVA03 d ON d.NRO_PEDIDO COLLATE DATABASE_DEFAULT = g.NRO_PEDIDO COLLATE DATABASE_DEFAULT AND d.TALON_PED = g.TALON_PED AND d.N_RENGLON = g.N_RENG_PED WHERE p.ID_GVA21 = __ID__ ORDER BY c.FECHA_MOV, c.N_COMP"
  $out.relacion = $true; $out.origen = 'GVA106'
  $out | ConvertTo-Json -Depth 4 -Compress
  exit
} catch { $out.gva106_error = $_.Exception.Message }
$tiene = { param($t, $c) [bool]($cols | Where-Object { $_.t -eq $t -and $_.c -eq $c }) }
$nro = "(SELECT NRO_PEDIDO FROM GVA21 WHERE ID_GVA21 = __ID__)"
$sel = "c.T_COMP AS T_COMP, c.N_COMP AS N_COMP, c.FECHA_MOV AS FECHA, r.COD_ARTICU AS COD_ARTICU, r.CANTIDAD AS CANTIDAD, r.TIPO_MOV AS TIPO_MOV"
$union = if (& $tiene 'STA20' 'ID_STA14') { "c.ID_STA14 = r.ID_STA14" } else { "c.TCOMP_IN_S = r.TCOMP_IN_S AND c.NCOMP_IN_S = r.NCOMP_IN_S" }
$sql = $null
if (& $tiene 'STA20' 'ID_GVA21') { $sql = "SELECT $sel FROM STA20 r JOIN STA14 c ON $union WHERE r.ID_GVA21 = __ID__" }
elseif (& $tiene 'STA14' 'ID_GVA21') { $sql = "SELECT $sel FROM STA20 r JOIN STA14 c ON $union WHERE c.ID_GVA21 = __ID__" }
else {
  foreach ($c in @('NRO_PEDIDO', 'N_PEDIDO', 'NRO_PEDI')) {
    if (& $tiene 'STA20' $c) { $sql = "SELECT $sel FROM STA20 r JOIN STA14 c ON $union WHERE r.$c = $nro"; break }
    if (& $tiene 'STA14' $c) { $sql = "SELECT $sel FROM STA20 r JOIN STA14 c ON $union WHERE c.$c = $nro"; break }
  }
}
if ($sql) { $out.filas = Q ($sql + " ORDER BY c.FECHA_MOV, c.N_COMP"); $out.relacion = $true } else { $out.filas = @(); $out.relacion = $false }
$out | ConvertTo-Json -Depth 4 -Compress
"""


def _remitos_pedido_local(id_pedido: int) -> dict:
    """Comprobantes de stock (remitos, devoluciones) hechos contra un pedido, agrupados por comprobante."""
    id_pedido = int(id_pedido)
    clave = ("remitos_pedido", id_pedido)
    if clave in _cache and time.time() - _cache[clave][0] < VIGENCIA:
        return _cache[clave][1]
    datos = _correr(_REMITOS_PEDIDO.replace("__ID__", str(id_pedido)))
    comprobantes: dict[tuple, dict] = {}
    for f in _filas(datos):
        t = str(f.get("T_COMP") or "").strip()
        n = str(f.get("N_COMP") or "")
        c = comprobantes.setdefault((t, n), {"t_comp": t, "tipo": _TIPOS.get(t, t), "numero": _numero_comprobante(n),
                                             "fecha": f.get("FECHA"), "renglones": []})
        try:
            cant = abs(float(f.get("CANTIDAD") or 0))
        except (TypeError, ValueError):
            cant = 0.0
        # Un remito saca del stock (S); una devolucion vuelve a entrar (E) y resta de lo entregado
        signo = 1 if str(f.get("TIPO_MOV") or "S").strip().upper() == "S" else -1
        c["renglones"].append({"codigo": str(f.get("COD_ARTICU") or "").strip(), "cantidad": round(cant * signo, 4)})
    columnas = datos.get("columnas") or []
    res = {"relacion": bool(datos.get("relacion")), "comprobantes": list(comprobantes.values()),
           "columnas": columnas if isinstance(columnas, list) else [columnas]}
    _cache[clave] = (time.time(), res)
    return res


# ------------------------------------------------------------------ remitos: pedido de cada uno y renglones
# Que pedido (o pedidos) tiene cada remito del ultimo año. Misma deteccion de columnas que
# _REMITOS_PEDIDO: la relacion puede estar en STA20 o STA14, por ID_GVA21 o por numero.
_REMITOS_CON_PEDIDO = r"""
$out = [ordered]@{}
$desde = "DATEADD(day, -400, GETDATE())"
# REFERENCIA_REMITO (TIPO P = pedido) une el remito (ID_STA14) con el pedido (talonario + numero).
# GVA55 (remito por numero) queda como respaldo. Encontrado con el diagnostico del 26/11/2026.
try { $out.filas = Q "SELECT DISTINCT c.N_COMP COLLATE DATABASE_DEFAULT AS N_COMP, p.ID_GVA21 AS ID_PEDIDO, p.NRO_PEDIDO COLLATE DATABASE_DEFAULT AS NRO_PEDIDO FROM REFERENCIA_REMITO r JOIN STA14 c ON c.ID_STA14 = r.ID_STA14 JOIN GVA21 p ON p.NRO_PEDIDO COLLATE DATABASE_DEFAULT = r.NRO_PEDIDO COLLATE DATABASE_DEFAULT AND p.TALON_PED = r.TALON_PED WHERE r.TIPO = 'P' AND c.T_COMP = 'REM' AND c.FECHA_MOV >= $desde UNION SELECT DISTINCT g.N_COMP COLLATE DATABASE_DEFAULT, p.ID_GVA21, p.NRO_PEDIDO COLLATE DATABASE_DEFAULT FROM GVA55 g JOIN GVA21 p ON p.NRO_PEDIDO COLLATE DATABASE_DEFAULT = g.NRO_PEDIDO COLLATE DATABASE_DEFAULT AND p.TALON_PED = g.TALON_PED WHERE g.T_COMP = 'REM' AND g.FECHA_PEDI >= DATEADD(day, -800, GETDATE())" }
catch { $out.referencia_error = $_.Exception.Message; $out.filas = Q "SELECT DISTINCT g.N_COMP COLLATE DATABASE_DEFAULT AS N_COMP, p.ID_GVA21 AS ID_PEDIDO, p.NRO_PEDIDO COLLATE DATABASE_DEFAULT AS NRO_PEDIDO FROM GVA55 g JOIN GVA21 p ON p.NRO_PEDIDO COLLATE DATABASE_DEFAULT = g.NRO_PEDIDO COLLATE DATABASE_DEFAULT AND p.TALON_PED = g.TALON_PED WHERE g.T_COMP = 'REM' AND g.FECHA_PEDI >= DATEADD(day, -800, GETDATE())" }
$out.relacion = $true
# GVA107: que factura se hizo con cada remito
# Factura de cada remito: GVA107 (remitos que salen de un pedido) y GVA54 (renglon del remito ->
# renglon de la factura, para los demas). Encontradas con los diagnosticos del 26/11/2026.
try { $out.facturas = Q "SELECT DISTINCT c.N_COMP COLLATE DATABASE_DEFAULT AS N_COMP, f.TCOMP_V COLLATE DATABASE_DEFAULT AS T_COMP, f.NCOMP_V COLLATE DATABASE_DEFAULT AS N_FAC FROM GVA107 f JOIN STA14 c ON c.TCOMP_IN_S COLLATE DATABASE_DEFAULT = f.TCOMP_IN_S COLLATE DATABASE_DEFAULT AND c.NCOMP_IN_S COLLATE DATABASE_DEFAULT = f.NCOMP_IN_S COLLATE DATABASE_DEFAULT WHERE c.T_COMP = 'REM' AND c.FECHA_MOV >= $desde UNION SELECT DISTINCT c.N_COMP COLLATE DATABASE_DEFAULT, f.T_COMP_V COLLATE DATABASE_DEFAULT, f.N_COMP COLLATE DATABASE_DEFAULT FROM GVA54 f JOIN STA14 c ON c.TCOMP_IN_S COLLATE DATABASE_DEFAULT = f.TCOMP_IN_S COLLATE DATABASE_DEFAULT AND c.NCOMP_IN_S COLLATE DATABASE_DEFAULT = f.NCOMP_IN_S COLLATE DATABASE_DEFAULT WHERE c.T_COMP = 'REM' AND c.FECHA_MOV >= $desde" }
catch { $out.facturas = @(); $out.facturas_error = $_.Exception.Message }
$out | ConvertTo-Json -Depth 4 -Compress
"""

# Renglones de un remito (por ID_STA14) con su descripcion y, si se encuentra la tabla, sus partidas.
_RENGLONES_REMITO = r"""
$out = [ordered]@{}
$cols = Q "SELECT TABLE_NAME AS t, COLUMN_NAME AS c FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME LIKE 'STA%' AND COLUMN_NAME IN ('ID_STA14','N_PARTIDA','NCOMP_IN_S','TCOMP_IN_S','COD_ARTICU','CANTIDAD')"
$tiene = { param($t, $c) [bool]($cols | Where-Object { $_.t -eq $t -and $_.c -eq $c }) }
$union = if (& $tiene 'STA20' 'ID_STA14') { "c.ID_STA14 = r.ID_STA14" } else { "c.TCOMP_IN_S = r.TCOMP_IN_S AND c.NCOMP_IN_S = r.NCOMP_IN_S" }
$out.renglones = Q "SELECT r.COD_ARTICU AS COD_ARTICU, a.DESCRIPCIO AS DESCRIPCION, r.CANTIDAD AS CANTIDAD, r.TIPO_MOV AS TIPO_MOV FROM STA20 r JOIN STA14 c ON $union LEFT JOIN STA11 a ON a.COD_ARTICU = r.COD_ARTICU WHERE c.ID_STA14 = __ID__"
# Partidas: una tabla STA (que no sea STA20) con N_PARTIDA, COD_ARTICU, CANTIDAD y el comprobante interno
$t = @($cols | Where-Object { $_.c -eq 'N_PARTIDA' -and $_.t -ne 'STA20' -and $_.t -ne 'STA08' } | ForEach-Object { $_.t } | Select-Object -Unique |
       Where-Object { (& $tiene $_ 'NCOMP_IN_S') -and (& $tiene $_ 'TCOMP_IN_S') -and (& $tiene $_ 'COD_ARTICU') -and (& $tiene $_ 'CANTIDAD') })
$out.tabla_partidas = if ($t.Count) { $t[0] } else { $null }
if ($t.Count) {
  try { $out.partidas = Q ("SELECT x.COD_ARTICU AS COD_ARTICU, x.N_PARTIDA AS N_PARTIDA, x.CANTIDAD AS CANTIDAD FROM " + $t[0] + " x JOIN STA14 c ON c.TCOMP_IN_S = x.TCOMP_IN_S AND c.NCOMP_IN_S = x.NCOMP_IN_S WHERE c.ID_STA14 = __ID__") }
  catch { $out.partidas = @(); $out.partidas_error = $_.Exception.Message }
} else { $out.partidas = @() }
$out | ConvertTo-Json -Depth 4 -Compress
"""


# Diagnostico: que une un remito con su pedido. Se parte de un par conocido (el ultimo remito
# que el pedido guarda) y se busca en toda la base: las columnas con "PEDI"/"GVA21" y, en cada
# tabla que las tenga, las filas que apuntan a ese pedido. Solo lectura.
# Diagnostico: donde queda la factura de un remito sin pedido. Busca el numero del remito
# (N_COMP y el numero interno NCOMP_IN_S) en todas las columnas de texto con nombre de
# comprobante o remito, y trae las facturas del cliente cercanas a la fecha. Solo lectura.
_DIAG_FACTURA_REMITO = r"""
$out = [ordered]@{}
function E($v) { ([string]$v).Replace("'", "''") }
$out.remito = Q "SELECT * FROM STA14 WHERE ID_STA14 = __REM__"
if (-not $out.remito.Count) { $out.error = 'No encontré ese remito.'; $out | ConvertTo-Json -Depth 6 -Compress; exit }
$r = $out.remito[0]
$ncomp = E $r.N_COMP; $nin = E $r.NCOMP_IN_S; $tin = E $r.TCOMP_IN_S; $cli = E $r.COD_PRO_CL; $fec = [string]$r.FECHA_MOV
$cols = Q "SELECT c.TABLE_NAME AS t, c.COLUMN_NAME AS c FROM INFORMATION_SCHEMA.COLUMNS c JOIN INFORMATION_SCHEMA.TABLES x ON x.TABLE_NAME = c.TABLE_NAME AND x.TABLE_TYPE = 'BASE TABLE' WHERE c.DATA_TYPE IN ('varchar','char','nvarchar','nchar') AND c.CHARACTER_MAXIMUM_LENGTH BETWEEN 8 AND 40 AND (c.COLUMN_NAME LIKE '%COMP%' OR c.COLUMN_NAME LIKE '%REMI%' OR c.COLUMN_NAME LIKE '%REM%') AND c.TABLE_NAME NOT IN ('STA14','STA20')"
$porTabla = @{}
foreach ($x in $cols) { if (-not $porTabla[$x.t]) { $porTabla[$x.t] = New-Object System.Collections.Generic.List[string] }; $porTabla[$x.t].Add($x.c) }
$out.coincidencias = @()
foreach ($x in $cols) {
  if ($x.c -match 'IN_S') {
    if ($x.c -match '^T') { continue }
    $w = "[$($x.c)] COLLATE DATABASE_DEFAULT = '$nin'"
    $tc = ($porTabla[$x.t] | Where-Object { $_ -match '^TCOMP.*IN_S' } | Select-Object -First 1)
    if ($tc) { $w += " AND [$tc] COLLATE DATABASE_DEFAULT = '$tin'" }
  } else { $w = "[$($x.c)] COLLATE DATABASE_DEFAULT = '$ncomp'" }
  try {
    $n = (Q "SELECT COUNT(*) AS n FROM [$($x.t)] WHERE $w")[0].n
    if ($n -gt 0) { $out.coincidencias += [pscustomobject]@{ tabla = $x.t; columna = $x.c; filas = $n; ejemplo = (Q "SELECT TOP 3 * FROM [$($x.t)] WHERE $w") } }
  } catch { }
}
$out.facturas_cliente = Q "SELECT TOP 8 * FROM GVA12 WHERE COD_CLIENT = '$cli' AND T_COMP IN ('FAC','N/D') AND FECHA_EMIS BETWEEN DATEADD(day, -15, '$fec') AND DATEADD(day, 60, '$fec') ORDER BY FECHA_EMIS"
$out | ConvertTo-Json -Depth 6 -Compress
"""


def _diag_factura_remito_local(id_remito: int) -> dict:
    datos = _correr(_DIAG_FACTURA_REMITO.replace("__REM__", str(int(id_remito))), tiempo=240)
    if datos.get("error"):
        return {"error": datos["error"]}
    return {"remito": [_sin_vacios(f) for f in _como_lista(datos.get("remito"))],
            "coincidencias": [{**{k: v for k, v in c.items() if k != "ejemplo"},
                               "ejemplo": [_sin_vacios(f) for f in _como_lista(c.get("ejemplo"))]}
                              for c in _como_lista(datos.get("coincidencias"))],
            "facturas_cliente": [_sin_vacios(f) for f in _como_lista(datos.get("facturas_cliente"))]}


def diag_factura_remito(id_remito: int) -> dict:
    if es_servidor():
        return _diag_factura_remito_local(id_remito)
    return _remoto("diag_factura_remito", {"remito": int(id_remito)}, tiempo=260)


_DIAG_PEDIDO_REMITO = r"""
$out = [ordered]@{}
function E($v) { ([string]$v).Replace("'", "''") }
$out.pedido = Q "SELECT * FROM GVA21 WHERE ID_GVA21 = __PED__"
$out.remito = Q "SELECT * FROM STA14 WHERE ID_STA14 = __REM__"
$nro = if ($out.pedido.Count) { [string]$out.pedido[0].NRO_PEDIDO } else { '' }
$out.columnas = Q "SELECT c.TABLE_NAME AS t, c.COLUMN_NAME AS c, c.DATA_TYPE AS tipo FROM INFORMATION_SCHEMA.COLUMNS c JOIN INFORMATION_SCHEMA.TABLES x ON x.TABLE_NAME = c.TABLE_NAME AND x.TABLE_TYPE = 'BASE TABLE' WHERE (c.COLUMN_NAME LIKE '%PEDI%' OR c.COLUMN_NAME LIKE '%GVA21%' OR c.COLUMN_NAME LIKE '%GVA03%') AND c.TABLE_NAME NOT IN ('GVA21')"
$out.coincidencias = @()
foreach ($x in $out.columnas) {
  $w = $null
  if ($x.tipo -match 'int|numeric|decimal') { if ($x.c -match 'GVA21|ID_') { $w = "[$($x.c)] = __PED__" } }
  elseif ($x.tipo -match 'char|text' -and $nro) {
    $d = ($nro -replace '\D', ''); if ($d.Length -gt 8) { $d = $d.Substring($d.Length - 8) }
    $w = "([$($x.c)] = '" + (E $nro) + "' OR (LEN(RTRIM([$($x.c)])) > 0 AND RTRIM([$($x.c)]) LIKE '%" + (E $d) + "'))"
  }
  if (-not $w) { continue }
  try {
    $n = (Q "SELECT COUNT(*) AS n FROM [$($x.t)] WHERE $w")[0].n
    if ($n -gt 0) {
      $out.coincidencias += [pscustomobject]@{ tabla = $x.t; columna = $x.c; filas = $n; ejemplo = (Q "SELECT TOP 3 * FROM [$($x.t)] WHERE $w") }
    }
  } catch { $out.coincidencias += [pscustomobject]@{ tabla = $x.t; columna = $x.c; error = $_.Exception.Message } }
}
$out | ConvertTo-Json -Depth 6 -Compress
"""


def _diag_pedido_remito_local(id_pedido: int, id_remito: int) -> dict:
    datos = _correr(_DIAG_PEDIDO_REMITO.replace("__PED__", str(int(id_pedido))).replace("__REM__", str(int(id_remito))), tiempo=180)
    res = {"pedido": [_sin_vacios(f) for f in _como_lista(datos.get("pedido"))],
           "remito": [_sin_vacios(f) for f in _como_lista(datos.get("remito"))],
           "columnas": [f"{c.get('t')}.{c.get('c')} ({c.get('tipo')})" for c in _como_lista(datos.get("columnas"))],
           "coincidencias": []}
    for c in _como_lista(datos.get("coincidencias")):
        res["coincidencias"].append({**{k: v for k, v in c.items() if k != "ejemplo"},
                                     "ejemplo": [_sin_vacios(f) for f in _como_lista(c.get("ejemplo"))]})
    return res


def diag_pedido_remito(id_pedido: int, id_remito: int) -> dict:
    if es_servidor():
        return _diag_pedido_remito_local(id_pedido, id_remito)
    return _remoto("diag_pedido_remito", {"pedido": int(id_pedido), "remito": int(id_remito)}, tiempo=200)


def _como_lista(v) -> list[dict]:
    """ConvertTo-Json devuelve un objeto suelto cuando hay una sola fila."""
    if isinstance(v, dict):
        return [v]
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _remitos_con_pedido_local() -> dict:
    clave = ("remitos_con_pedido",)
    if clave in _cache and time.time() - _cache[clave][0] < VIGENCIA:
        return _cache[clave][1]
    datos = _correr(_REMITOS_CON_PEDIDO)
    por_remito: dict[str, list[dict]] = {}
    for f in _como_lista(datos.get("filas")):
        n = str(f.get("N_COMP") or "").strip()
        lista = por_remito.setdefault(n, [])
        x = {"id": f.get("ID_PEDIDO"), "numero": str(f.get("NRO_PEDIDO") or "").strip()}
        if x not in lista:
            lista.append(x)
    facturas: dict[str, list[dict]] = {}
    for f in _como_lista(datos.get("facturas")):
        n = str(f.get("N_COMP") or "").strip()
        t = str(f.get("T_COMP") or "").strip()
        x = {"tipo": _TIPOS.get(t, t), "numero": _numero_comprobante(str(f.get("N_FAC") or ""))}
        if x not in facturas.setdefault(n, []):
            facturas[n].append(x)
    res = {"relacion": bool(datos.get("relacion")), "remitos": por_remito, "facturas": facturas,
           "facturas_leidas": not datos.get("facturas_error")}
    _cache[clave] = (time.time(), res)
    return res


def remitos_con_pedido() -> dict:
    """{numero de remito tal cual Tango: [pedidos]} para los remitos del ultimo año (base, solo lectura)."""
    if es_servidor():
        return _remitos_con_pedido_local()
    return _remoto("remitos_con_pedido", {})


def _renglones_remito_local(id_remito: int) -> dict:
    id_remito = int(id_remito)
    clave = ("renglones_remito", id_remito)
    if clave in _cache and time.time() - _cache[clave][0] < VIGENCIA:
        return _cache[clave][1]
    datos = _correr(_RENGLONES_REMITO.replace("__ID__", str(id_remito)))
    partidas: dict[str, list[dict]] = {}
    for f in _como_lista(datos.get("partidas")):
        cod = str(f.get("COD_ARTICU") or "").strip()
        partidas.setdefault(cod, []).append({"partida": str(f.get("N_PARTIDA") or "").strip(),
                                             "cantidad": round(abs(_num(f.get("CANTIDAD")) or 0), 4)})
    renglones = []
    for f in _como_lista(datos.get("renglones")):
        cod = str(f.get("COD_ARTICU") or "").strip()
        signo = 1 if str(f.get("TIPO_MOV") or "S").strip().upper() == "S" else -1
        renglones.append({"codigo": cod, "descripcion": str(f.get("DESCRIPCION") or "").strip(),
                          "cantidad": round(abs(_num(f.get("CANTIDAD")) or 0) * signo, 4),
                          "partidas": partidas.get(cod, [])})
    res = {"renglones": renglones, "partidas_leidas": bool(datos.get("tabla_partidas")) and not datos.get("partidas_error")}
    _cache[clave] = (time.time(), res)
    return res


def renglones_remito(id_remito: int) -> dict:
    """Articulos (y partidas, si se encuentran) de un remito, por su ID_STA14 (base, solo lectura)."""
    id_remito = int(id_remito)
    if es_servidor():
        return _renglones_remito_local(id_remito)
    return _remoto("renglones_remito", {"id": id_remito})


def remitos_pedido(id_pedido: int) -> dict:
    """Remitos y devoluciones hechos contra un pedido (base, solo lectura)."""
    id_pedido = int(id_pedido)
    if es_servidor():
        return _remitos_pedido_local(id_pedido)
    return _remoto("remitos_pedido", {"id": id_pedido})


# ------------------------------------------------------------------ importaciones
# Carpetas (CPA65) con su proveedor, renglones (CPA66: pedido, nacionalizado, precio) y
# las partidas que creo cada despacho (STA08). Si la union con proveedores falla por
# nombres de columna, se lee la cabecera sola.
_IMPORTACIONES = r"""
$out = [ordered]@{}
$out.columnas = @((Q "SELECT COLUMN_NAME AS c FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'CPA65'") | ForEach-Object { $_.c })
try { $out.carpetas = Q "SELECT c.*, p.NOM_PROVEE AS NOMBRE_PROVEEDOR FROM CPA65 c LEFT JOIN CPA01 p ON p.COD_PROVEE = c.COD_PROVEE" }
catch { $out.carpetas = Q "SELECT * FROM CPA65" }
$out.renglones = Q "SELECT ID_CARPETA, COD_ARTICU, CANT_PEDID, CANT_NACIO, CANT_FACTU, PREC_ORIG, CAN_EQUIVA FROM CPA66"
$out.despachos = Q "SELECT DISTINCT ID_CARPETA, N_DESPACHO, N_PARTIDA, FECHA FROM STA08 WHERE ISNULL(ID_CARPETA, '') <> ''"
$out | ConvertTo-Json -Depth 4 -Compress
"""
VIGENCIA_IMPORTACIONES = 600


def _importaciones_local() -> dict:
    from . import importaciones
    clave = ("importaciones",)
    if clave in _cache and time.time() - _cache[clave][0] < VIGENCIA_IMPORTACIONES:
        return _cache[clave][1]
    res = importaciones.armar(_correr(_IMPORTACIONES))
    _cache[clave] = (time.time(), res)
    return res


def importaciones_datos(forzar: bool = False) -> dict:
    """Carpetas de importacion y, por articulo, lo que esta en camino y el precio de compra."""
    if forzar:
        _cache.pop(("importaciones",), None)
    if es_servidor():
        return _importaciones_local()
    return _remoto("importaciones", {"refrescar": "1"} if forzar else {})


# ------------------------------------------------------------------ valorizacion
# Lo necesario para valorizar el stock de Central en dolares (ver valorizacion.py):
# saldos por partida (STA10) de Central y de las partidas que vinieron por despacho,
# cabeceras de partidas (STA08), cantidades facturadas (CPA66), gastos de carpeta (CPA71)
# y su reparto por partida (CPA74). Los articulos sin partidas salen de STA19.
_VALORIZACION = r"""
$out = [ordered]@{}
$out.partidas = Q "SELECT ID_STA08, N_PARTIDA, N_DESPACHO, ID_CARPETA, FECHA FROM STA08"
$out.saldos = Q "SELECT s.COD_ARTICU, s.N_PARTIDA, s.COD_DEPOSI, s.CANTIDAD, s.CANT_DESPA, s.COSTO_EX, s.ID_STA08 FROM STA10 s LEFT JOIN STA08 p ON p.ID_STA08 = s.ID_STA08 WHERE (LTRIM(RTRIM(s.COD_DEPOSI)) = '1' AND s.CANTIDAD <> 0) OR ISNULL(p.ID_CARPETA, '') <> ''"
$out.renglones = Q "SELECT ID_CARPETA, COD_ARTICU, CANT_FACTU, CAN_EQUIVA FROM CPA66"
$out.gastos = Q "SELECT * FROM CPA71"
try { $out.distribucion = Q "SELECT * FROM CPA74" } catch { $out.distribucion = @() }
$out.articulos = Q "SELECT COD_ARTICU, DESCRIPCIO FROM STA11"
try { $out.sin_partidas = Q "SELECT * FROM STA19 WHERE LTRIM(RTRIM(COD_DEPOSI)) = '1'" } catch { $out.sin_partidas = @() }
$out | ConvertTo-Json -Depth 4 -Compress
"""
VIGENCIA_VALORIZACION = 600


def _valorizacion_local() -> dict:
    from . import valorizacion
    clave = ("valorizacion",)
    if clave in _cache and time.time() - _cache[clave][0] < VIGENCIA_VALORIZACION:
        return _cache[clave][1]
    res = valorizacion.calcular(_correr(_VALORIZACION, tiempo=180))
    res["calculado"] = time.strftime("%Y-%m-%d %H:%M")
    _cache[clave] = (time.time(), res)
    return res


def valorizacion_datos(forzar: bool = False) -> dict:
    """Stock de Central valorizado en dolares, renglon por renglon (base, solo lectura)."""
    if forzar:
        _cache.pop(("valorizacion",), None)
    if es_servidor():
        return _valorizacion_local()
    return _remoto("valorizacion", {"refrescar": "1"} if forzar else {}, tiempo=200)


# ------------------------------------------------------------------ ventas de un articulo
# Ultimas facturas (GVA12) con sus renglones (GVA53) de un articulo, para el precio sugerido.
# PRECIO_NET es el precio unitario neto del renglon; PREC_ULC_E, el costo de ultima compra en
# moneda extranjera que Tango anoto al vender. La cotizacion de la factura (COTIZ) puede no
# existir con ese nombre: si falla, se lee sin ella.
_VENTAS_ARTICULO = r"""
$out = [ordered]@{}
$desde = "FROM GVA53 r JOIN GVA12 f ON f.T_COMP = r.T_COMP AND f.N_COMP = r.N_COMP LEFT JOIN GVA14 c ON c.COD_CLIENT = f.COD_CLIENT WHERE r.COD_ARTICU = '__COD__' AND r.T_COMP IN ('FAC', 'N/C') ORDER BY f.FECHA_EMIS DESC"
try { $out.filas = Q "SELECT TOP 120 f.FECHA_EMIS AS F_FECHA, f.COD_CLIENT AS F_CLIENTE, c.RAZON_SOCI AS F_RAZON, f.MON_CTE AS F_MON_CTE, f.COTIZ AS F_COTIZ, r.* $desde" }
catch { $out.aviso = $_.Exception.Message
        $out.filas = Q "SELECT TOP 120 f.FECHA_EMIS AS F_FECHA, f.COD_CLIENT AS F_CLIENTE, c.RAZON_SOCI AS F_RAZON, f.MON_CTE AS F_MON_CTE, r.* $desde" }
$out | ConvertTo-Json -Depth 4 -Compress
"""


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _en_pesos(v) -> bool:
    """MON_CTE: verdadero = moneda corriente (pesos)."""
    if isinstance(v, bool):
        return v
    return str(v or "").strip().upper() in ("TRUE", "S", "SI", "1", "T")


def _ventas_articulo_local(codigo: str) -> dict:
    codigo = _validar_articulo(codigo)
    clave = ("ventas_articulo", codigo)
    if clave in _cache and time.time() - _cache[clave][0] < VIGENCIA:
        return _cache[clave][1]
    datos = _correr(_VENTAS_ARTICULO.replace("__COD__", codigo))
    filas = []
    for f in _filas(datos):
        t = str(f.get("T_COMP") or "").strip()
        precio = _num(_campo(f, "PRECIO_NET", "PRECIO", "PRECIO_PAN"))
        cantidad = _num(_campo(f, "CANTIDAD", "CANT_FACT")) or 0.0
        cotiz = _num(f.get("F_COTIZ"))
        pesos = _en_pesos(f.get("F_MON_CTE"))
        usd = None
        if precio is not None:
            if pesos and cotiz and cotiz > 1:
                usd = precio / cotiz
            elif not pesos:
                usd = precio
        filas.append({
            "fecha": f.get("F_FECHA"), "t_comp": t, "tipo": _TIPOS.get(t, t),
            "numero": _numero_comprobante(str(f.get("N_COMP") or "")),
            "codigo_cliente": str(f.get("F_CLIENTE") or "").strip(), "cliente": str(f.get("F_RAZON") or "").strip(),
            "cantidad": round(cantidad, 4), "precio": round(precio, 4) if precio is not None else None,
            "moneda": "$" if pesos else "US$", "cotizacion": round(cotiz, 4) if cotiz else None,
            "precio_usd": round(usd, 4) if usd is not None else None,
            "costo_al_vender_usd": _num(f.get("PREC_ULC_E")) or None,
        })
    res = {"filas": filas, "aviso": datos.get("aviso")}
    _cache[clave] = (time.time(), res)
    return res


def ventas_articulo(codigo: str) -> dict:
    """Ultimas facturas y notas de credito de un articulo (base, solo lectura)."""
    codigo = _validar_articulo(codigo)
    if es_servidor():
        return _ventas_articulo_local(codigo)
    return _remoto("ventas_articulo", {"art": codigo})


# ------------------------------------------------------------------ aduana de una carpeta
# Diagnostico (solo lectura): que comprobantes de proveedor estan atados a una carpeta
# (CPA77) o son de Aduana cerca de la fecha del despacho, y en que cuentas contables
# quedaron. No se sabe de antemano en que tabla guarda Tango las imputaciones de
# Compras: se buscan las tablas CPA con columnas de cuenta y de comprobante, y se
# muestra lo que tengan para esos comprobantes. Sirve para que Estela diga que cuentas
# son costo (derechos, tasa de estadistica) y cuales no (IVA, percepciones).
_ADUANA = r"""
$out = [ordered]@{}
function E($v) { ([string]$v).Replace("'", "''") }
$out.carpetas = Q "SELECT * FROM CPA65 WHERE RIGHT(RTRIM(ID_CARPETA), 8) = '__CARPETA8__'"
$ids = @($out.carpetas | ForEach-Object { "'" + (E $_.ID_CARPETA) + "'" })
if (-not $ids.Count) { $out.error = 'No encontré esa carpeta.'; $out | ConvertTo-Json -Depth 5 -Compress; exit }
$lista = $ids -join ','
$out.despachos = Q "SELECT DISTINCT N_DESPACHO, FECHA FROM STA08 WHERE ID_CARPETA IN ($lista)"
try { $out.cpa77 = Q "SELECT * FROM CPA77 WHERE ID_CARPETA IN ($lista)" } catch { $out.cpa77 = @(); $out.cpa77_error = $_.Exception.Message }
$out.proveedores_aduana = Q "SELECT COD_PROVEE, NOM_PROVEE FROM CPA01 WHERE NOM_PROVEE LIKE '%ADUANA%' OR NOM_PROVEE LIKE '%A.F.I.P%' OR NOM_PROVEE LIKE '%AFIP%' OR NOM_PROVEE LIKE '%ARCA%'"
$prov = @($out.proveedores_aduana | ForEach-Object { "'" + (E $_.COD_PROVEE) + "'" })
# Comprobantes: los de CPA77 y los de Aduana dentro de los 60 dias del despacho
$conds = @()
foreach ($r in $out.cpa77) {
  $p = $r.PSObject.Properties
  if ($p['T_COMP'] -and $p['N_COMP']) {
    $c = "(T_COMP = '" + (E $r.T_COMP) + "' AND N_COMP = '" + (E $r.N_COMP) + "'"
    if ($p['COD_PROVEE'] -and $r.COD_PROVEE) { $c += " AND COD_PROVEE = '" + (E $r.COD_PROVEE) + "'" }
    $conds += $c + ")"
  }
}
$fechas = @($out.despachos | Where-Object { $_.FECHA } | ForEach-Object { $_.FECHA })
if ($prov.Count -and $fechas.Count) {
  $f = ($fechas | Sort-Object)[0]
  $conds += "(COD_PROVEE IN (" + ($prov -join ',') + ") AND FECHA_EMIS BETWEEN DATEADD(day, -60, '$f') AND DATEADD(day, 60, '$f'))"
}
$out.comprobantes = @()
if ($conds.Count) {
  try { $out.comprobantes = Q ("SELECT TOP 40 * FROM CPA04 WHERE " + ($conds -join ' OR ') + " ORDER BY FECHA_EMIS") }
  catch { $out.comprobantes_error = $_.Exception.Message
          $sinFecha = @($conds | Where-Object { $_ -notmatch 'FECHA_EMIS' })
          if ($sinFecha.Count) { $out.comprobantes = Q ("SELECT TOP 40 * FROM CPA04 WHERE " + ($sinFecha -join ' OR ')) } }
}
# Tablas de Compras con cuenta contable y comprobante
$cols = Q "SELECT TABLE_NAME AS t, COLUMN_NAME AS c FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME LIKE 'CPA%' OR TABLE_NAME LIKE 'CP_%'"
$porTabla = @{}
foreach ($x in $cols) { if (-not $porTabla[$x.t]) { $porTabla[$x.t] = New-Object System.Collections.Generic.List[string] }; $porTabla[$x.t].Add($x.c) }
$out.tablas_con_cuenta = @()
$out.imputaciones = [ordered]@{}
foreach ($t in ($porTabla.Keys | Sort-Object)) {
  $c = $porTabla[$t]
  $cuenta = @($c | Where-Object { $_ -match 'CTA|CUENTA' })
  if (-not $cuenta.Count) { continue }
  $out.tablas_con_cuenta += [pscustomobject]@{ tabla = $t; cuentas = ($cuenta -join ', '); columnas = $c.Count }
  if (-not ($c -contains 'N_COMP' -and $c -contains 'T_COMP')) { continue }
  $w = @()
  foreach ($k in $out.comprobantes) {
    $x = "(T_COMP = '" + (E $k.T_COMP) + "' AND N_COMP = '" + (E $k.N_COMP) + "'"
    if ($c -contains 'COD_PROVEE') { $x += " AND COD_PROVEE = '" + (E $k.COD_PROVEE) + "'" }
    $w += $x + ")"
  }
  if (-not $w.Count) { continue }
  try { $out.imputaciones[$t] = Q ("SELECT TOP 200 * FROM $t WHERE " + ($w -join ' OR ')) }
  catch { $out.imputaciones[$t] = @([pscustomobject]@{ error = $_.Exception.Message }) }
}
# Plan de cuentas, si esta en esta base (para poner nombre a las cuentas)
$plan = Q "SELECT TOP 1 TABLE_NAME AS t FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME IN ('CPA92','CPA92B','GVA65','CO_CUENTA','CUENTAS')"
$out.plan_tabla = if ($plan.Count) { $plan[0].t } else { $null }
$out | ConvertTo-Json -Depth 5 -Compress
"""


def _sin_vacios(fila: dict) -> dict:
    return {k: v for k, v in fila.items() if v not in (None, "", 0, 0.0, False) and not str(k).startswith("FILLER")}


def _aduana_local(carpeta: int) -> dict:
    carpeta = int(carpeta)
    if not 0 < carpeta < 10 ** 8:
        raise ValueError("Número de carpeta inválido.")
    datos = _correr(_ADUANA.replace("__CARPETA8__", f"{carpeta:08d}"), tiempo=120)
    for k in ("carpetas", "despachos", "cpa77", "proveedores_aduana", "comprobantes", "tablas_con_cuenta"):
        v = datos.get(k)
        datos[k] = [] if v is None else (v if isinstance(v, list) else [v])
    for k in ("carpetas", "cpa77", "comprobantes"):
        datos[k] = [_sin_vacios(f) for f in datos[k]]
    imp = datos.get("imputaciones") or {}
    datos["imputaciones"] = {t: [_sin_vacios(f) for f in (v if isinstance(v, list) else [v])] for t, v in imp.items() if v}
    return datos


def aduana_carpeta(carpeta: int) -> dict:
    """Comprobantes de proveedor (y de Aduana) de una carpeta, con sus cuentas. Diagnostico."""
    if es_servidor():
        return _aduana_local(carpeta)
    return _remoto("aduana", {"carpeta": int(carpeta)}, tiempo=140)


# ------------------------------------------------------------------ desde otras PCs
# La base esta solo en el servidor de Tango. Una Herramienta que corre en otra PC
# no la puede leer: le pide el dato a la Herramienta del servidor (/api/base/...),
# que hace la consulta local y devuelve el resultado.

def _servidor_tango() -> tuple[str, int] | None:
    from . import config
    try:
        cfg = config.cargar()
    except Exception:
        return None
    host = urllib.parse.urlparse(cfg.servidor).hostname if cfg.servidor else None
    return (host, cfg.puerto) if host else None


def es_servidor() -> bool:
    """True si esta PC es la del servidor de Tango (donde esta la base)."""
    if os.environ.get("HERRAMIENTA_TANGO_DEMO") == "1":
        return True
    if os.environ.get("HERRAMIENTA_TANGO_BASE_LOCAL") == "1":
        return True
    destino = _servidor_tango()
    if not destino:
        return True                     # sin configurar: se intenta local
    host = destino[0].lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    nombre = socket.gethostname().lower()
    return host == nombre or host.split(".")[0] == nombre.split(".")[0]


def _remoto(ruta: str, parametros: dict, tiempo: int = 70):
    destino = _servidor_tango()
    if not destino:
        raise BaseNoDisponible("No sé cuál es el servidor de Tango para pedirle estos datos.")
    url = f"http://{destino[0]}:{destino[1]}/api/base/{ruta}?{urllib.parse.urlencode(parametros)}"
    try:
        with urllib.request.urlopen(url, timeout=tiempo) as r:
            datos = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            datos = json.loads(e.read().decode("utf-8"))
        except Exception:
            raise BaseNoDisponible(f"La Herramienta del servidor ({destino[0]}) respondió con error {e.code}. "
                                   "Puede que tenga una versión vieja: actualizala.") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise BaseNoDisponible(f"No se pudo pedir el dato a la Herramienta del servidor ({destino[0]}:{destino[1]}). "
                               f"¿Está prendida? {e}") from None
    if not datos.get("ok"):
        error = datos.get("error") or "La Herramienta del servidor no pudo leer la base."
        if error.strip().rstrip(".") == "Consulta desconocida":
            error = ("La Herramienta del servidor tiene una versión anterior y todavía no conoce esta consulta. "
                     "Se actualiza sola en hasta 15 minutos; probá de nuevo en un rato.")
        raise BaseNoDisponible(error)
    return datos.get("datos")


def usos_lista(id_lista: int, numero_lista: int) -> dict:
    """Cotizaciones (GVA08) y facturas (GVA12, por año) que usan la lista."""
    if es_servidor():
        return _usos_local(id_lista, numero_lista)
    return _remoto("usos", {"id": int(id_lista), "nro": int(numero_lista)})


def comprobantes_lista(numero_lista: int, anio: int) -> list[dict]:
    """Comprobantes de venta (GVA12) de un año hechos con la lista."""
    if es_servidor():
        return _comprobantes_local(numero_lista, anio)
    return _remoto("comprobantes", {"nro": int(numero_lista), "anio": int(anio)})


def renglones_comprobante(t_comp: str, n_comp: str) -> list[dict]:
    """Renglones (GVA53) de un comprobante."""
    if es_servidor():
        return _renglones_local(t_comp, n_comp)
    _renglones_validar(t_comp, n_comp)
    return _remoto("renglones", {"t": t_comp, "n": n_comp})


def movimientos_articulo(codigo: str) -> list[dict]:
    """Ultimos movimientos de stock (STA14/STA20) de un articulo."""
    codigo = _validar_articulo(codigo)
    if es_servidor():
        return _movimientos_local(codigo)
    return _remoto("movimientos", {"art": codigo})


def responder_remoto(ruta: str, qs: dict):
    """Lo que atiende el servidor para las otras PCs: siempre consulta local."""
    p = lambda k: (qs.get(k) or [""])[0]
    if ruta == "usos":
        return _usos_local(int(p("id")), int(p("nro")))
    if ruta == "comprobantes":
        return _comprobantes_local(int(p("nro")), int(p("anio")))
    if ruta == "renglones":
        return _renglones_local(p("t"), p("n"))
    if ruta == "movimientos":
        return _movimientos_local(p("art"))
    if ruta == "importaciones":
        if p("refrescar") == "1":
            _cache.pop(("importaciones",), None)
        return _importaciones_local()
    if ruta == "valorizacion":
        if p("refrescar") == "1":
            _cache.pop(("valorizacion",), None)
        return _valorizacion_local()
    if ruta == "ventas_articulo":
        return _ventas_articulo_local(p("art"))
    if ruta == "aduana":
        return _aduana_local(int(p("carpeta")))
    if ruta == "diag_factura_remito":
        return _diag_factura_remito_local(int(p("remito")))
    if ruta == "diag_pedido_remito":
        return _diag_pedido_remito_local(int(p("pedido")), int(p("remito")))
    if ruta == "remitos_con_pedido":
        return _remitos_con_pedido_local()
    if ruta == "renglones_remito":
        return _renglones_remito_local(int(p("id")))
    if ruta == "remitos_pedido":
        return _remitos_pedido_local(int(p("id")))
    raise ValueError("Consulta desconocida.")
