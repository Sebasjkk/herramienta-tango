"""
Genera el archivo de datos de version que PyInstaller incrusta en el .exe
(lo que Windows muestra en Propiedades > Detalles).

Uso: python scripts/archivo_version.py 1.5 version_info.txt
"""

import sys

version = sys.argv[1]
partes = [int(p) for p in version.split(".")] + [0, 0, 0, 0]
tupla = tuple(partes[:4])

contenido = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={tupla}, prodvers={tupla}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('0C0A04B0', [
        StringStruct('CompanyName', 'Herramienta Tango'),
        StringStruct('FileDescription', 'Herramienta Tango - consultas sobre Tango Gestion'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'HerramientaTango'),
        StringStruct('OriginalFilename', 'HerramientaTango.exe'),
        StringStruct('ProductName', 'Herramienta Tango'),
        StringStruct('ProductVersion', '{version}'),
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0C0A, 1200])])
  ]
)
"""
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write(contenido)
