"""
Arma un .zip con rutas en formato estandar (barras /), igual en cualquier sistema.

Uso: python scripts/comprimir.py CARPETA DESTINO.zip [--incluir-carpeta]
  --incluir-carpeta: el zip contiene la carpeta (CARPETA/...) y no solo su contenido.
"""

import sys
import zipfile
from pathlib import Path

carpeta = Path(sys.argv[1]).resolve()
destino = Path(sys.argv[2])
incluir = "--incluir-carpeta" in sys.argv[3:]
base = carpeta.parent if incluir else carpeta

with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for ruta in sorted(carpeta.rglob("*")):
        if ruta.is_file() and "__pycache__" not in ruta.parts:
            z.write(ruta, ruta.relative_to(base).as_posix())
print(f"{destino}: {destino.stat().st_size} bytes")
