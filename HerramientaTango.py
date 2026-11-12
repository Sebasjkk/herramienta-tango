"""Punto de entrada de Herramienta Tango (es el que empaqueta PyInstaller)."""

import sys

from herramienta_tango.app import main

if __name__ == "__main__":
    sys.exit(main())
