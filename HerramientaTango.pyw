"""
Punto de entrada de Herramienta Tango.

Se ejecuta con pythonw.exe (el Python oficial, sin ventana de consola):
    python\\pythonw.exe app\\HerramientaTango.pyw
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from herramienta_tango.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
