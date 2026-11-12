"""
Actualizacion automatica desde los Releases de GitHub.

Cada cierto tiempo consulta la ultima version publicada. Si es mas nueva que
la que esta corriendo:

1. Descarga el .exe nuevo a "HerramientaTango.new.exe".
2. Verifica su SHA-256 contra el archivo .sha256 publicado junto al release.
   Si no coincide, lo borra y no instala nada.
3. Renombra el .exe en uso a "HerramientaTango.old.exe" (Windows permite
   renombrar un .exe que esta corriendo, aunque no sobrescribirlo) y pone el
   nuevo en su lugar. Si algo falla en este paso, vuelve todo como estaba.
4. Avisa al programa para que se reinicie con el .exe nuevo.

Al arrancar, el programa borra el .old.exe que haya quedado.

Solo actua cuando corre como .exe (PyInstaller). Corriendo desde el codigo
fuente informa si hay version nueva, pero no instala nada.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

log = logging.getLogger("herramienta_tango")

NOMBRE_EXE = "HerramientaTango.exe"
TIMEOUT = 60


def version_a_tupla(texto: str) -> tuple[int, ...] | None:
    """'v1.12' o '1.12' -> (1, 12). Devuelve None si no es una version numerica."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (texto or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def es_mas_nueva(disponible: str, actual: str) -> bool:
    d, a = version_a_tupla(disponible), version_a_tupla(actual)
    return bool(d and a and d > a)


def sha256_de(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _get(url: str, aceptar: str = "application/json") -> bytes:
    pedido = urllib.request.Request(url, headers={
        "Accept": aceptar,
        "User-Agent": "HerramientaTango-actualizador",
    })
    with urllib.request.urlopen(pedido, timeout=TIMEOUT) as r:
        return r.read()


def _descargar(url: str, destino: Path) -> None:
    pedido = urllib.request.Request(url, headers={"User-Agent": "HerramientaTango-actualizador"})
    with urllib.request.urlopen(pedido, timeout=TIMEOUT) as r, open(destino, "wb") as f:
        while True:
            bloque = r.read(1 << 20)
            if not bloque:
                break
            f.write(bloque)


@dataclass
class EstadoActualizacion:
    version_actual: str
    estado: str = "sin_revisar"      # sin_revisar | al_dia | disponible | instalando | reiniciando | error | desactivado
    version_disponible: str | None = None
    mensaje: str = ""
    ultima_revision: str | None = None
    automatica: bool = True

    def como_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Release:
    version: str
    url_exe: str
    url_sha256: str


class Actualizador:
    def __init__(self, version_actual: str, repo: str, cada_minutos: int, automatica: bool,
                 al_instalar: Callable[[Path], None], ruta_exe: Path | None = None,
                 obtener_json: Callable[[str], dict] | None = None,
                 descargar: Callable[[str, Path], None] | None = None,
                 obtener_texto: Callable[[str], str] | None = None):
        self.repo = repo.strip().strip("/")
        self.cada_segundos = max(5, cada_minutos) * 60
        self.al_instalar = al_instalar
        self.empaquetado = getattr(sys, "frozen", False) or ruta_exe is not None
        self.ruta_exe = ruta_exe or Path(sys.executable).resolve()
        self.estado = EstadoActualizacion(version_actual=version_actual, automatica=automatica)
        self._obtener_json = obtener_json or (lambda url: json.loads(_get(url)))
        self._obtener_texto = obtener_texto or (lambda url: _get(url, "application/octet-stream").decode("utf-8", "replace"))
        self._descargar = descargar or _descargar
        self._lock = threading.Lock()
        self._parar = threading.Event()

    # ------------------------------------------------------------- rutas
    @property
    def ruta_nueva(self) -> Path:
        return self.ruta_exe.with_name(self.ruta_exe.stem + ".new.exe")

    @property
    def ruta_vieja(self) -> Path:
        return self.ruta_exe.with_name(self.ruta_exe.stem + ".old.exe")

    def limpiar_restos(self) -> None:
        """Borra el .old.exe de una actualizacion anterior (reintenta si sigue bloqueado)."""
        for _ in range(10):
            try:
                for ruta in (self.ruta_vieja, self.ruta_nueva):
                    if ruta.exists():
                        ruta.unlink()
                return
            except OSError:
                time.sleep(3)

    # ------------------------------------------------------------- consulta
    def ultima_release(self) -> Release:
        # La variable de entorno solo se usa en la prueba automatica del workflow
        url = os.environ.get("HERRAMIENTA_TANGO_URL_RELEASES") or \
            f"https://api.github.com/repos/{self.repo}/releases/latest"
        datos = self._obtener_json(url)
        version = (datos.get("tag_name") or "").lstrip("v")
        activos = {a.get("name"): a.get("browser_download_url") for a in datos.get("assets") or []}
        url_exe = activos.get(NOMBRE_EXE)
        url_sha = activos.get(NOMBRE_EXE + ".sha256")
        if not version or not url_exe or not url_sha:
            raise ValueError("La última versión publicada no trae el .exe y su .sha256.")
        return Release(version, url_exe, url_sha)

    def revisar(self, instalar: bool | None = None) -> None:
        """Consulta GitHub y, si corresponde, instala. No lanza excepciones."""
        if not self._lock.acquire(blocking=False):
            return  # ya hay una revision o instalacion en curso
        try:
            e = self.estado
            e.ultima_revision = datetime.now().isoformat(timespec="seconds")
            try:
                release = self.ultima_release()
            except Exception as ex:
                e.estado, e.mensaje = "error", f"No se pudo consultar GitHub: {ex}"
                log.warning(e.mensaje)
                return
            if not es_mas_nueva(release.version, e.version_actual):
                e.estado, e.version_disponible, e.mensaje = "al_dia", release.version, ""
                return
            e.estado, e.version_disponible = "disponible", release.version
            e.mensaje = f"Hay una versión nueva: {release.version}"
            log.info(e.mensaje)
            if instalar is None:
                instalar = e.automatica
            if instalar and self.empaquetado:
                self._instalar(release)
            elif not self.empaquetado:
                e.mensaje += " (corriendo desde el código fuente: no se instala sola)"
        finally:
            self._lock.release()

    # ------------------------------------------------------------- instalacion
    def _instalar(self, release: Release) -> None:
        e = self.estado
        e.estado, e.mensaje = "instalando", f"Descargando la versión {release.version}..."
        log.info(e.mensaje)
        nueva, vieja, actual = self.ruta_nueva, self.ruta_vieja, self.ruta_exe
        try:
            esperado = self._obtener_texto(release.url_sha256).split()[0].lower()
            if not re.fullmatch(r"[0-9a-f]{64}", esperado):
                raise ValueError("el archivo .sha256 publicado no es válido")
            self._descargar(release.url_exe, nueva)
            obtenido = sha256_de(nueva)
            if obtenido != esperado:
                raise ValueError("el archivo descargado no coincide con el publicado (SHA-256 distinto)")
        except Exception as ex:
            nueva.unlink(missing_ok=True)
            e.estado, e.mensaje = "error", f"No se instaló la versión {release.version}: {ex}"
            log.error(e.mensaje)
            return

        # Cambio de archivos, con vuelta atras si algo falla
        try:
            vieja.unlink(missing_ok=True)
            os.replace(actual, vieja)
        except OSError as ex:
            nueva.unlink(missing_ok=True)
            e.estado, e.mensaje = "error", f"No se pudo apartar el .exe en uso: {ex}"
            log.error(e.mensaje)
            return
        try:
            os.replace(nueva, actual)
        except OSError as ex:
            try:
                os.replace(vieja, actual)
            except OSError:
                pass
            nueva.unlink(missing_ok=True)
            e.estado, e.mensaje = "error", f"No se pudo poner el .exe nuevo en su lugar: {ex}"
            log.error(e.mensaje)
            return

        e.estado, e.mensaje = "reiniciando", f"Versión {release.version} instalada. Reiniciando..."
        log.info(e.mensaje)
        self.al_instalar(actual)

    # ------------------------------------------------------------- ciclo
    def iniciar(self) -> None:
        def ciclo():
            self.limpiar_restos()
            while not self._parar.is_set():
                self.revisar()
                if self.estado.estado == "reiniciando":
                    return
                self._parar.wait(self.cada_segundos)
        threading.Thread(target=ciclo, name="actualizador", daemon=True).start()

    def detener(self) -> None:
        self._parar.set()


def reiniciar_con(ruta_exe: Path, argumentos: list[str]) -> None:
    """Abre el .exe nuevo como un proceso independiente, en su propia ventana."""
    import subprocess

    entorno = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI", "_MEI"))}
    entorno["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # que no reuse la carpeta temporal del proceso viejo
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen([str(ruta_exe), *argumentos], cwd=str(ruta_exe.parent), env=entorno,
                     creationflags=flags, close_fds=True)
