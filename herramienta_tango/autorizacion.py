"""
Perfiles de usuario y permisos.

Ver datos lo puede cualquiera en la red de la oficina, sin entrar. Para
modificar hay que entrar con un perfil (nombre y clave). Hay dos roles:

- usuario: modifica precios (cambiar, agregar y quitar articulos de una lista).
- administrador: ademas crea y elimina listas, y maneja los perfiles.

Los perfiles se guardan en usuarios.json, en la carpeta del programa, con la
clave como hash PBKDF2 (nunca la clave). Un perfil nuevo o con la clave
restablecida tiene que cambiarla al entrar.

El primer administrador se crea desde el panel del servidor; el panel tambien
sirve para restablecer la clave de cualquiera si se la olvida.

Las sesiones viven en memoria: al reiniciar el programa hay que volver a entrar.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from . import config

ITERACIONES = 200_000
DURACION_SESION = 10 * 3600          # segundos
MAX_INTENTOS = 8                     # intentos fallidos por IP cada 10 minutos
VENTANA_INTENTOS = 600
MIN_CLAVE = 6
ROLES = ("usuario", "administrador")


class PedidoInvalido(ValueError):
    """Dato mal cargado: el mensaje se muestra tal cual."""


def hash_clave(clave: str, sal: str | None = None, iteraciones: int = ITERACIONES) -> str:
    sal = sal or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", clave.encode("utf-8"), bytes.fromhex(sal), iteraciones).hex()
    return f"pbkdf2_sha256${iteraciones}${sal}${h}"


def clave_correcta(clave: str, guardado: str) -> bool:
    try:
        _, iteraciones, sal, _h = guardado.split("$")
        return hmac.compare_digest(hash_clave(clave, sal, int(iteraciones)), guardado)
    except (ValueError, TypeError):
        return False


def _validar_clave(clave: str) -> str:
    if len(clave or "") < MIN_CLAVE:
        raise PedidoInvalido(f"La clave tiene que tener al menos {MIN_CLAVE} caracteres.")
    return clave


def _limpiar_nombre(nombre: str) -> str:
    nombre = " ".join((nombre or "").split())
    if not nombre:
        raise PedidoInvalido("Escribí el nombre.")
    if len(nombre) > 40:
        raise PedidoInvalido("El nombre puede tener hasta 40 letras.")
    return nombre


def ruta_usuarios() -> Path:
    return config.CARPETA / "usuarios.json"


class Usuarios:
    """Perfiles guardados en usuarios.json. Todas las operaciones son atomicas."""

    def __init__(self, ruta: Path | None = None):
        self._ruta_fija = ruta
        self._lock = threading.RLock()

    @property
    def ruta(self) -> Path:
        return self._ruta_fija or ruta_usuarios()

    def _leer(self) -> list[dict]:
        try:
            return json.loads(self.ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError):
            raise PedidoInvalido("No se pudo leer usuarios.json.")

    def _guardar(self, lista: list[dict]) -> None:
        temporal = self.ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")
        temporal.replace(self.ruta)

    @staticmethod
    def publico(u: dict) -> dict:
        return {k: u.get(k) for k in ("id", "nombre", "rol", "debe_cambiar", "creado", "ultimo_ingreso")}

    def todos(self) -> list[dict]:
        with self._lock:
            return [self.publico(u) for u in self._leer()]

    def nombres(self) -> list[str]:
        return sorted((u["nombre"] for u in self.todos()), key=str.lower)

    def hay_administrador(self) -> bool:
        return any(u["rol"] == "administrador" for u in self.todos())

    def buscar(self, id_usuario: str) -> dict | None:
        with self._lock:
            return next((self.publico(u) for u in self._leer() if u["id"] == id_usuario), None)

    def crear(self, nombre: str, clave: str, rol: str = "usuario", debe_cambiar: bool = True) -> dict:
        nombre = _limpiar_nombre(nombre)
        _validar_clave(clave)
        if rol not in ROLES:
            raise PedidoInvalido("El rol tiene que ser usuario o administrador.")
        with self._lock:
            lista = self._leer()
            if any(u["nombre"].lower() == nombre.lower() for u in lista):
                raise PedidoInvalido(f"Ya existe el perfil {nombre}.")
            u = {"id": secrets.token_hex(6), "nombre": nombre, "rol": rol, "hash": hash_clave(clave),
                 "debe_cambiar": debe_cambiar, "creado": datetime.now().isoformat(timespec="seconds"),
                 "ultimo_ingreso": None}
            lista.append(u)
            self._guardar(lista)
            return self.publico(u)

    def _modificar(self, id_usuario: str, cambio) -> dict:
        with self._lock:
            lista = self._leer()
            u = next((x for x in lista if x["id"] == id_usuario), None)
            if not u:
                raise PedidoInvalido("Ese perfil ya no existe.")
            cambio(u, lista)
            self._guardar(lista)
            return self.publico(u)

    def cambiar_rol(self, id_usuario: str, rol: str) -> dict:
        if rol not in ROLES:
            raise PedidoInvalido("El rol tiene que ser usuario o administrador.")

        def cambio(u, lista):
            if u["rol"] == "administrador" and rol != "administrador" and \
                    sum(1 for x in lista if x["rol"] == "administrador") == 1:
                raise PedidoInvalido("Tiene que quedar al menos un administrador.")
            u["rol"] = rol
        return self._modificar(id_usuario, cambio)

    def restablecer_clave(self, id_usuario: str, clave: str) -> dict:
        """La pone un administrador: el perfil la tiene que cambiar al entrar."""
        _validar_clave(clave)
        return self._modificar(id_usuario, lambda u, _l: u.update(hash=hash_clave(clave), debe_cambiar=True))

    def cambiar_clave_propia(self, id_usuario: str, actual: str, nueva: str) -> dict:
        _validar_clave(nueva)
        if actual == nueva:
            raise PedidoInvalido("La clave nueva tiene que ser distinta de la anterior.")

        def cambio(u, _l):
            if not clave_correcta(actual or "", u["hash"]):
                raise PedidoInvalido("La clave actual no es correcta.")
            u.update(hash=hash_clave(nueva), debe_cambiar=False)
        return self._modificar(id_usuario, cambio)

    def eliminar(self, id_usuario: str) -> None:
        with self._lock:
            lista = self._leer()
            u = next((x for x in lista if x["id"] == id_usuario), None)
            if not u:
                return
            if u["rol"] == "administrador" and sum(1 for x in lista if x["rol"] == "administrador") == 1:
                raise PedidoInvalido("No se puede eliminar al único administrador.")
            self._guardar([x for x in lista if x["id"] != id_usuario])

    def verificar(self, nombre: str, clave: str) -> dict | None:
        with self._lock:
            lista = self._leer()
            u = next((x for x in lista if x["nombre"].lower() == " ".join((nombre or "").split()).lower()), None)
            if not u or not clave_correcta(clave or "", u["hash"]):
                return None
            u["ultimo_ingreso"] = datetime.now().isoformat(timespec="seconds")
            self._guardar(lista)
            return self.publico(u)


class Sesiones:
    def __init__(self, usuarios: Usuarios):
        self.usuarios = usuarios
        self._lock = threading.Lock()
        self._sesiones: dict[str, tuple[str, float]] = {}      # token -> (id de usuario, vence)
        self._fallos: dict[str, list[float]] = {}

    def entrar(self, nombre: str, clave: str, ip: str) -> tuple[str | None, str]:
        if not self.usuarios.todos():
            return None, "Todavía no hay perfiles. Se crean desde el panel del servidor."
        ahora = time.time()
        with self._lock:
            fallos = [t for t in self._fallos.get(ip, []) if ahora - t < VENTANA_INTENTOS]
            self._fallos[ip] = fallos
            if len(fallos) >= MAX_INTENTOS:
                return None, "Demasiados intentos. Esperá unos minutos."
        u = self.usuarios.verificar(nombre, clave)
        if not u:
            with self._lock:
                self._fallos.setdefault(ip, []).append(ahora)
            time.sleep(0.5)
            return None, "El nombre o la clave no son correctos."
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sesiones[token] = (u["id"], ahora + DURACION_SESION)
        return token, f"Hola, {u['nombre']}."

    def usuario(self, token: str | None) -> dict | None:
        """El perfil de la sesion (leido de nuevo: si lo eliminaron o le cambiaron el rol, se nota enseguida)."""
        if not token:
            return None
        with self._lock:
            dato = self._sesiones.get(token)
            if not dato:
                return None
            id_usuario, vence = dato
            if time.time() > vence:
                del self._sesiones[token]
                return None
        u = self.usuarios.buscar(id_usuario)
        if not u:
            self.salir(token)
        return u

    def salir(self, token: str | None) -> None:
        with self._lock:
            self._sesiones.pop(token or "", None)

    def cerrar_de(self, id_usuario: str, salvo: str | None = None) -> None:
        with self._lock:
            for t in [t for t, (i, _v) in self._sesiones.items() if i == id_usuario and t != salvo]:
                del self._sesiones[t]


USUARIOS = Usuarios()
SESIONES = Sesiones(USUARIOS)
