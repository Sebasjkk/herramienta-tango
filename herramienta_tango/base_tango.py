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
import os
import subprocess
import sys
import time

SERVIDOR_SQL = os.environ.get("HERRAMIENTA_TANGO_SQL", r"localhost\AXSQLEXPRESS")
BASE = os.environ.get("HERRAMIENTA_TANGO_BASE", "SIANCO_SA")
VIGENCIA = 300
_cache: dict[tuple, tuple[float, dict]] = {}


class BaseNoDisponible(Exception):
    pass


_FUNCION = r"""
$ErrorActionPreference = 'Stop'
$cs = 'Server=__SERVIDOR__;Database=__BASE__;Integrated Security=True;Connect Timeout=8;ApplicationIntent=ReadOnly'
function Q($sql) {
  $t = New-Object System.Data.DataTable
  $a = New-Object System.Data.SqlClient.SqlDataAdapter($sql, $cs)
  [void]$a.Fill($t)
  ,@($t.Rows | ForEach-Object { $r = $_; $o = [ordered]@{}
      foreach ($c in $t.Columns) { $v = $r[$c.ColumnName]
        if ($v -is [DBNull]) { $v = $null } elseif ($v -is [datetime]) { $v = $v.ToString('yyyy-MM-dd') } elseif ($v -is [string]) { $v = $v.Trim() }
        $o[$c.ColumnName] = $v }
      [pscustomobject]$o })
}
"""

_USOS_LISTA = r"""
$out = [ordered]@{}
$out.cotizaciones = Q "SELECT TOP 50 q.N_COTIZ AS numero, q.FECHA_EMIS AS fecha, q.FECHA_VIG AS vigencia, q.ESTADO AS estado, q.COD_CLIENT AS codigo_cliente, c.RAZON_SOCI AS cliente FROM GVA08 q LEFT JOIN GVA14 c ON c.ID_GVA14 = q.ID_GVA14 WHERE q.ID_GVA10 = __ID__ ORDER BY q.FECHA_EMIS DESC"
$out.cotizaciones_total = (Q "SELECT COUNT(*) AS n FROM GVA08 WHERE ID_GVA10 = __ID__")[0].n
$out.facturas_por_anio = Q "SELECT YEAR(FECHA_EMIS) AS anio, COUNT(*) AS n FROM GVA12 WHERE NRO_DE_LIS = __NRO__ GROUP BY YEAR(FECHA_EMIS) ORDER BY 1"
$out | ConvertTo-Json -Depth 4 -Compress
"""


def _correr(script: str) -> dict:
    if sys.platform != "win32":
        raise BaseNoDisponible("La base de Tango solo se lee desde el servidor (Windows).")
    completo = (_FUNCION.replace("__SERVIDOR__", SERVIDOR_SQL).replace("__BASE__", BASE) + script)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", completo],
                           capture_output=True, text=True, timeout=40,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BaseNoDisponible(f"No se pudo consultar la base de Tango: {e}") from None
    if r.returncode != 0 or not r.stdout.strip():
        detalle = " ".join((r.stderr or r.stdout or "").split())[:400]
        if "Login failed" in detalle or "Error de inicio de sesi" in detalle:
            raise BaseNoDisponible("La Herramienta no tiene permiso para leer la base de Tango. " + detalle)
        raise BaseNoDisponible(f"No se pudo consultar la base de Tango: {detalle or 'sin respuesta'}")
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        raise BaseNoDisponible("La base de Tango devolvió algo que no se pudo leer.") from None


def usos_lista(id_lista: int, numero_lista: int) -> dict:
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
