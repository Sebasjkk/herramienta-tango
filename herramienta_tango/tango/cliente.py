"""
Cliente HTTP de la API de Tango Gestion.

Es la UNICA parte del programa que habla con Tango. Hoy solo expone
lecturas (GET): no hay ningun metodo que cree, modifique o borre datos.
Si en el futuro se agrega escritura, tiene que ir en metodos separados y
explicitos, nunca mezclada con las lecturas.

Autenticacion: encabezados ApiAuthorization (token de desarrollador) y
Company (ID interno de la empresa).
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Iterator


class TangoError(Exception):
    """Error al consultar Tango, con un mensaje pensado para mostrar al usuario."""


class TokenInvalido(TangoError):
    pass


class SinConexion(TangoError):
    pass


class ClienteTango:
    TAM_PAGINA = 500

    def __init__(self, servidor: str, company: str, token: str, timeout: int = 30):
        self.servidor = servidor.rstrip("/")
        self.company = str(company)
        self._token = token
        self.timeout = timeout

    # ------------------------------------------------------------------ base
    def _get(self, ruta: str, parametros: dict) -> dict:
        url = f"{self.servidor}/{ruta}?{urllib.parse.urlencode(parametros)}"
        pedido = urllib.request.Request(url, method="GET", headers={
            "ApiAuthorization": self._token,
            "Company": self.company,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(pedido, timeout=self.timeout) as resp:
                datos = json.loads(resp.read().decode("utf-8-sig"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise TokenInvalido(
                    "Tango rechazó el token (401). Borrá el archivo token.dat de la carpeta del "
                    "programa, volvé a abrirlo y pegá un token aceptado en Tango "
                    "(Desarrollador > Aceptar).") from None
            raise TangoError(f"Tango respondió con error HTTP {e.code}.") from None
        except urllib.error.URLError as e:
            raise SinConexion(f"No se pudo conectar con Tango en {self.servidor} ({e.reason}).") from None
        except (TimeoutError, socket.timeout):
            raise SinConexion("Tango tardó demasiado en responder.") from None
        except json.JSONDecodeError:
            raise TangoError("Tango respondió algo que no es JSON.") from None

        if isinstance(datos, dict) and datos.get("succeeded") is False:
            raise TangoError(f"Tango no pudo resolver el pedido: {datos.get('message') or 'sin detalle'}")
        return datos

    def _paginas(self, ruta: str, parametros: dict) -> Iterator[dict]:
        pagina, total = 0, 1
        while pagina < total:
            datos = self._get(ruta, {**parametros, "pageSize": self.TAM_PAGINA, "pageIndex": pagina})
            resultado = datos.get("resultData") or {}
            yield from (resultado.get("list") or [])
            total = int(resultado.get("totalPages") or 0)
            pagina += 1

    # --------------------------------------------------------------- lecturas
    def listar(self, proceso: int, vista: str = "") -> list[dict]:
        """Todos los registros de un proceso (api/Get), recorriendo las paginas."""
        return list(self._paginas("api/Get", {"process": proceso, "view": vista}))

    def obtener(self, proceso: int, id_registro: int) -> dict:
        """Un registro por su ID interno (api/GetById)."""
        datos = self._get("api/GetById", {"process": proceso, "id": id_registro})
        return datos.get("value") or datos.get("resultData") or datos

    def consulta_live(self, proceso: int, desde: date | None = None, hasta: date | None = None) -> list[dict]:
        """Todos los renglones de una consulta Live (api/GetApiLiveQueryData)."""
        parametros: dict = {"process": proceso}
        if desde:
            parametros["fromDate"] = desde.strftime("%d/%m/%Y")
        if hasta:
            parametros["toDate"] = hasta.strftime("%d/%m/%Y")
        return list(self._paginas("api/GetApiLiveQueryData", parametros))
