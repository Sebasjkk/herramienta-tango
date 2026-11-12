"""
Estado del programa en marcha: configuracion, conexion con Tango y acciones del panel.

Permite configurar o cambiar el servidor y el token sin reiniciar: se arma un
servicio nuevo y se reemplaza el anterior.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable

from . import VERSION, config, credenciales, sistema
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

    def info(self) -> dict:
        act = self.actualizador.estado.como_dict() if self.actualizador else None
        return {
            "version": VERSION,
            "configurado": self.configurado,
            "servidor": self.cfg.servidor,
            "tango": self.estado_tango,
            "puerto": self.cfg.puerto,
            "direcciones": sistema.direcciones_locales(),
            "inicio_automatico": sistema.inicio_automatico_activo(),
            "inicio_automatico_disponible": sistema.es_windows() and sistema.instalacion() is not None,
            "actualizacion": act,
        }
