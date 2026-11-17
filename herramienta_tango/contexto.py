"""
Estado del programa en marcha: configuracion, conexion con Tango y acciones del panel.

Permite configurar o cambiar el servidor y el token sin reiniciar: se arma un
servicio nuevo y se reemplaza el anterior.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from typing import Callable

from . import VERSION, autorizacion, config, credenciales, sistema
from .tango import ClienteTango, ServicioTango, SinConexion, TangoError, TokenInvalido

log = logging.getLogger("herramienta_tango")


class NoConfigurado(TangoError):
    """Todavia no se cargaron el servidor y el token."""


class Contexto:
    def __init__(self, cfg: config.Config, fabrica_cliente: Callable[..., ClienteTango] = ClienteTango):
        self.cfg = cfg
        self._fabrica_cliente = fabrica_cliente
        self._lock = threading.Lock()
        self._servicio: ServicioTango | None = None
        self.estado_tango: dict = {"estado": "sin_configurar", "mensaje": "", "revisado": None}
        self.actualizador = None          # lo asigna app.py
        self.al_cerrar: Callable[[], None] = lambda: None
        self.como_servicio = False        # corre como tarea programada de Windows (modo servidor)
        self.cambio_modo: dict = {"estado": "", "mensaje": ""}   # activacion/desactivacion en curso

    # ------------------------------------------------------------- servicio
    def _armar_servicio(self, servidor: str, token: str) -> ServicioTango:
        cliente = self._fabrica_cliente(servidor, self.cfg.company, token, self.cfg.timeout)
        return ServicioTango(cliente, vigencia_saldos=self.cfg.vigencia_saldos)

    def cargar_guardado(self) -> bool:
        """Arma el servicio con el servidor y el token guardados. Devuelve si quedo configurado."""
        token = credenciales.leer_token()
        if self.cfg.servidor and token:
            with self._lock:
                self._servicio = self._armar_servicio(self.cfg.servidor, token)
        return self.configurado

    @property
    def configurado(self) -> bool:
        return self._servicio is not None

    def servicio(self) -> ServicioTango:
        s = self._servicio
        if s is None:
            raise NoConfigurado("El programa todavía no está configurado. Abrilo en la PC donde está instalado.")
        return s

    def probar_conexion(self) -> dict:
        try:
            saldos, _ = self.servicio().saldos_por_partida(forzar=True)
            con_saldo = sum(1 for s in saldos if abs(s.saldo) > 0.0001)
            self.estado_tango = {"estado": "ok", "mensaje": f"{len(saldos)} partidas, {con_saldo} con saldo"}
        except NoConfigurado as e:
            self.estado_tango = {"estado": "sin_configurar", "mensaje": str(e)}
        except TokenInvalido as e:
            self.estado_tango = {"estado": "token_invalido", "mensaje": str(e)}
        except TangoError as e:
            self.estado_tango = {"estado": "sin_conexion", "mensaje": str(e)}
        self.estado_tango["revisado"] = datetime.now().isoformat(timespec="seconds")
        log.info(f"Conexión con Tango: {self.estado_tango['estado']} {self.estado_tango['mensaje']}")
        return self.estado_tango

    # ------------------------------------------------------------- acciones del panel
    def configurar(self, servidor: str, token: str) -> tuple[bool, str]:
        """Prueba servidor y token contra Tango; si andan, los guarda y los usa."""
        servidor = config.normalizar_servidor(servidor)
        token = (token or "").strip()
        if not token:
            token = credenciales.leer_token() or ""   # cambiar solo el servidor
        if not config.servidor_valido(servidor):
            return False, "La dirección tiene que incluir el puerto, por ejemplo http://NOMBRE-PC:17000."
        if servidor.rstrip("/").endswith(f":{self.cfg.puerto}"):
            return False, (f"Esa es la dirección de este programa, no la de Tango. "
                           f"Tango usa otro puerto, normalmente 17000: por ejemplo http://localhost:17000 "
                           f"si este programa está en el servidor de Tango.")
        if not credenciales.formato_valido(token):
            return False, "El token tiene que tener 36 caracteres, con el formato XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX."

        nuevo = self._armar_servicio(servidor, token)
        try:
            nuevo.depositos(forzar=True)
        except TokenInvalido:
            return False, "Tango rechazó el token. Revisá que esté aceptado en Tango (Desarrollador > Aceptar)."
        except SinConexion:
            return False, f"No se pudo conectar con Tango en {servidor}. Revisá la dirección."
        except TangoError as e:
            return False, str(e)

        try:
            config.guardar_servidor(servidor)
            credenciales.guardar_token(token)
        except OSError as e:
            return False, f"Funciona, pero no se pudo guardar la configuración: {e}"

        self.cfg = config.cargar()
        with self._lock:
            self._servicio = nuevo
        self.probar_conexion()
        return True, "Listo: conectado a Tango."

    # ------------------------------------------------------------- modo servidor
    def _cambio(self, estado: str, mensaje: str = "") -> None:
        self.cambio_modo = {"estado": estado, "mensaje": mensaje}
        if mensaje:
            log.info(f"Modo servidor: {mensaje}")

    def activar_modo_servidor(self) -> tuple[bool, str]:
        inst = sistema.instalacion()
        if not sistema.es_windows() or not inst:
            return False, "Solo disponible con el programa instalado en Windows."
        if self.cambio_modo["estado"] == "esperando_permiso":
            return False, "Ya se pidió el permiso: buscá la ventana de Windows."
        threading.Thread(target=self._activar, args=(inst,), name="modo-servidor", daemon=True).start()
        return True, "Windows va a pedir permiso de administrador."

    def _activar(self, inst) -> None:
        error = config.CARPETA / "modo_servidor_error.txt"
        try:
            error.unlink(missing_ok=True)
            # Volver a guardar el token cifrado a nivel equipo, para que lo lea la cuenta SYSTEM
            token = credenciales.leer_token()
            if token:
                credenciales.guardar_token(token)
            self._cambio("esperando_permiso", "")
            sistema.ejecutar_powershell(
                sistema.script_activar_servidor(inst, self.cfg.puerto, os.getpid()), como_admin=True)
        except OSError as e:
            self._cambio("error", str(e))
            return
        # El script corre aparte: avisa con un archivo cuando termino
        for _ in range(180):
            if error.exists():
                self._cambio("error", "Windows no dejó activarlo: " + error.read_text(encoding="utf-8-sig").strip())
                return
            if sistema.modo_servidor_activo():
                break
            time.sleep(0.5)
        else:
            self._cambio("error", "No hubo respuesta. Probá de nuevo.")
            return
        try:
            sistema.activar_inicio_automatico(False)   # ya arranca la tarea programada
        except OSError:
            pass
        self._cambio("pasando", "Activado: el programa se reinicia como servidor.")
        threading.Timer(2.0, self.al_cerrar).start()   # el script espera a que esta copia se cierre

    def desactivar_modo_servidor(self) -> tuple[bool, str]:
        if not sistema.es_windows():
            return False, "Solo disponible en Windows."
        try:
            # Como SYSTEM no hace falta pedir permiso; desde una copia comun, si
            sistema.ejecutar_powershell(sistema.script_desactivar_servidor(), como_admin=not self.como_servicio)
        except OSError as e:
            return False, str(e)
        if self.como_servicio:
            self._cambio("desactivado", "Modo servidor desactivado.")
            threading.Timer(2.0, self.al_cerrar).start()
            return True, "Desactivado. Para seguir usándolo, abrí Herramienta Tango desde el escritorio."
        return True, "Desactivado."

    def info(self) -> dict:
        act = self.actualizador.estado.como_dict() if self.actualizador else None
        inst = sistema.instalacion()
        return {
            "version": VERSION,
            "configurado": self.configurado,
            "servidor": self.cfg.servidor,
            "tango": self.estado_tango,
            "puerto": self.cfg.puerto,
            "direcciones": sistema.direcciones_locales(),
            "nombre_equipo": sistema.nombre_equipo(),
            "usuarios": autorizacion.USUARIOS.todos(),
            "modo_servidor": {
                "disponible": sistema.es_windows() and inst is not None,
                "activo": sistema.modo_servidor_activo(),
                "como_servicio": self.como_servicio,
                **self.cambio_modo,
            },
            "inicio_automatico": sistema.inicio_automatico_activo(),
            "inicio_automatico_disponible": sistema.es_windows() and sistema.instalacion() is not None,
            "actualizacion": act,
        }
