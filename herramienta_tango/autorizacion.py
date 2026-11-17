"""
Permiso para modificar precios.

Ver precios lo puede cualquiera en la red de la oficina. Modificarlos pide una
clave que se define en el panel del servidor (en config.ini se guarda solo un
hash PBKDF2, no la clave). Quien entra dice su nombre, que queda en el
registro de cada cambio.

Las sesiones viven en memoria: al reiniciar el programa hay que volver a entrar.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

from . import config

ITERACIONES = 200_000
DURACION_SESION = 10 * 3600          # segundos
MAX_INTENTOS = 8                     # intentos fallidos por IP cada 10 minutos
VENTANA_INTENTOS = 600


def hash_clave(clave: str, sal: str | None = None, iteraciones: int = ITERACIONES) -> str:
    sal = sal or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(sal), iteraciones).hex()
    return f"pbkdf2_sha256${iteraciones}${sal}${h}"


def clave_correcta(clave: str, guardado: str) -> bool:
    try:
        _, iteraciones, sal, h = guardado.split("$")
        return hmac.compare_digest(hash_clave(clave, sal, int(iteraciones)), guardado)
    except (ValueError, TypeError):
        return False


def edicion_habilitada() -> bool:
    return bool(config.leer_clave_precios())


def definir_clave(clave: str) -> tuple[bool, str]:
    clave = clave or ""
    if not clave:
        config.guardar_clave_precios("")
        SESIONES.cerrar_todas()
        return True, "Listo: ya no se pueden modificar precios."
    if len(clave) < 6:
        return False, "La clave tiene que tener al menos 6 caracteres."
    config.guardar_clave_precios(hash_clave(clave))
    SESIONES.cerrar_todas()      # quien estaba adentro tiene que entrar con la clave nueva
    return True, "Listo: la clave quedó guardada."


class Sesiones:
    def __init__(self):
        self._lock = threading.Lock()
        self._sesiones: dict[str, tuple[str, float]] = {}
        self._fallos: dict[str, list[float]] = {}

    def entrar(self, nombre: str, clave: str, ip: str) -> tuple[str | None, str]:
        nombre = " ".join((nombre or "").split())[:40]
        if not nombre:
            return None, "Escribí tu nombre: queda registrado en cada cambio."
        guardado = config.leer_clave_precios()
        if not guardado:
            return None, "Todavía no se definió una clave. Se define en el panel del servidor."
        ahora = time.time()
        with self._lock:
            fallos = [t for t in self._fallos.get(ip, []) if ahora - t < VENTANA_INTENTOS]
            self._fallos[ip] = fallos
            if len(fallos) >= MAX_INTENTOS:
                return None, "Demasiados intentos. Esperá unos minutos."
        if not clave_correcta(clave or "", guardado):
            with self._lock:
                self._fallos.setdefault(ip, []).append(ahora)
            time.sleep(0.5)
            return None, "La clave no es correcta."
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sesiones[token] = (nombre, ahora + DURACION_SESION)
        return token, f"Hola, {nombre}."

    def quien(self, token: str | None) -> str | None:
        if not token:
            return None
        with self._lock:
            dato = self._sesiones.get(token)
            if not dato:
                return None
            nombre, vence = dato
            if time.time() > vence:
                del self._sesiones[token]
                return None
            return nombre

    def salir(self, token: str | None) -> None:
        with self._lock:
            self._sesiones.pop(token or "", None)

    def cerrar_todas(self) -> None:
        with self._lock:
            self._sesiones.clear()


SESIONES = Sesiones()
