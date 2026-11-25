"""
Cliente HTTP de la API de Tango Gestion.

Es la UNICA parte del programa que habla con Tango. Las lecturas (GET) y
las escrituras (crear, modificar, borrar) estan en metodos separados. Las
escrituras solo las usa el editor de precios (precios.py); probadas contra
Tango 25.1 el 17/11/2026 con una lista de prueba:
    POST   api/Create?process=N        cuerpo: el registro (como lo da GetById, sin ID)
    PUT    api/Update?process=N        cuerpo: el registro completo, con su ID
    DELETE api/Delete?process=N&id=ID

Autenticacion: encabezados ApiAuthorization (token de desarrollador) y
Company (ID interno de la empresa).
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Iterator



def _motivo(datos: dict) -> str:
    """El motivo real de un error de Tango.

    Tango pone un texto generico en "message" ("Se detectó una situación
    inesperada") y la explicacion en exceptionInfo.messages / detailMessages.
    """
    if not isinstance(datos, dict):
        return ""
    info = datos.get("exceptionInfo") if isinstance(datos.get("exceptionInfo"), dict) else {}
    partes = []
    for clave in ("messages", "detailMessages"):
        for m in info.get(clave) or []:
            texto = (m.get("message") or m.get("text") or "") if isinstance(m, dict) else str(m)
            texto = " ".join(texto.split())
            if texto and texto not in partes:
                partes.append(texto)
    if partes:
        return " ".join(partes)
    return datos.get("message") or info.get("message") or ""

class TangoError(Exception):
    """Error al consultar Tango, con un mensaje pensado para mostrar al usuario."""


class TokenInvalido(TangoError):
    pass


class SinConexion(TangoError):
    pass


# Ultima IP con la que se llego a cada nombre de servidor. Windows a veces deja de
# resolver el nombre de la PC de Tango ("[Errno 11001] getaddrinfo failed") aunque
# Tango siga andando: con esto se sigue usando la IP que ya funciono.
_RUTA_IPS = None          # Path del archivo donde se recuerdan (lo pone _ruta_ips)
_ips_conocidas: dict[str, str] = {}


def _ruta_ips():
    global _RUTA_IPS
    if _RUTA_IPS is None:
        try:
            from .. import config
            _RUTA_IPS = config.CARPETA / "ip_tango.json"
        except Exception:
            _RUTA_IPS = False
    return _RUTA_IPS or None


def _ip_recordada(host: str) -> str | None:
    if host not in _ips_conocidas:
        ruta = _ruta_ips()
        try:
            _ips_conocidas.update(json.loads(ruta.read_text(encoding="utf-8")))
        except Exception:
            pass
    return _ips_conocidas.get(host)


def _recordar_ip(host: str, ip: str) -> None:
    if _ips_conocidas.get(host) == ip:
        return
    _ips_conocidas[host] = ip
    ruta = _ruta_ips()
    if ruta:
        try:
            ruta.write_text(json.dumps(_ips_conocidas), encoding="utf-8")
        except OSError:
            pass


def _es_esta_pc(host: str) -> bool:
    nombre = socket.gethostname().lower().split(".")[0]
    return host.lower().split(".")[0] == nombre


def _es_ip(host: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host)
        return True
    except (OSError, ValueError):
        return False


def _falla_de_nombre(e: urllib.error.URLError) -> bool:
    return isinstance(e.reason, socket.gaierror)


class ClienteTango:
    TAM_PAGINA = 500

    def __init__(self, servidor: str, company: str, token: str, timeout: int = 30):
        self.servidor = servidor.rstrip("/")
        self.company = str(company)
        self._token = token
        self.timeout = timeout
        self._ip_anotada = False
        self._alternativo: tuple[float, str] | None = None   # (hasta cuando, servidor por IP)

    # ------------------------------------------------------------------ base
    def _abrir(self, metodo: str, ruta: str, parametros: dict, datos_cuerpo: bytes | None,
               encabezados: dict, servidor: str):
        url = f"{servidor}/{ruta}?{urllib.parse.urlencode(parametros)}"
        pedido = urllib.request.Request(url, data=datos_cuerpo, method=metodo, headers=encabezados)
        with urllib.request.urlopen(pedido, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8-sig")

    def _otra_direccion(self, host: str) -> str | None:
        """Si el nombre del servidor no se resuelve: la IP que ya anduvo, o esta misma PC."""
        if _es_ip(host):
            return None
        if _es_esta_pc(host):
            return "127.0.0.1"
        return _ip_recordada(host)

    def _pedir(self, metodo: str, ruta: str, parametros: dict, cuerpo: dict | None = None) -> dict:
        encabezados = {"ApiAuthorization": self._token, "Company": self.company, "Accept": "application/json"}
        datos_cuerpo = None
        if cuerpo is not None:
            datos_cuerpo = json.dumps(cuerpo).encode("utf-8")
            encabezados["Content-Type"] = "application/json"
        partes = urllib.parse.urlsplit(self.servidor)
        host = partes.hostname or ""
        alternativo = self._alternativo
        try:
            try:
                if alternativo and alternativo[0] > time.monotonic():
                    # el nombre no se resolvia hace un rato: no esperar otra vez a que falle
                    texto = self._abrir(metodo, ruta, parametros, datos_cuerpo, encabezados, alternativo[1])
                else:
                    texto = self._abrir(metodo, ruta, parametros, datos_cuerpo, encabezados, self.servidor)
                    self._alternativo = None
                    if host and not _es_ip(host) and not self._ip_anotada:
                        self._ip_anotada = True
                        try:
                            _recordar_ip(host, socket.gethostbyname(host))
                        except OSError:
                            pass
            except urllib.error.URLError as e:
                if isinstance(e, urllib.error.HTTPError) or not _falla_de_nombre(e):
                    raise
                ip = self._otra_direccion(host)
                if not ip:
                    raise SinConexion(
                        f"No se pudo conectar con Tango en {self.servidor}: esta PC no encuentra la "
                        f"computadora «{host}» en la red. Revisá que esté prendida, o cargá su IP "
                        f"en lugar del nombre en Ajustes > Servidor y token "
                        f"(por ejemplo http://192.168.0.10:{partes.port or 17000}).") from None
                otro = f"{partes.scheme}://{ip}" + (f":{partes.port}" if partes.port else "")
                texto = self._abrir(metodo, ruta, parametros, datos_cuerpo, encabezados, otro)
                self._alternativo = (time.monotonic() + 300, otro)
            datos = json.loads(texto) if texto.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise TokenInvalido(
                    "Tango rechazó el token (401). Borrá el archivo token.dat de la carpeta del "
                    "programa, volvé a abrirlo y pegá un token aceptado en Tango "
                    "(Desarrollador > Aceptar).") from None
            detalle = ""
            try:
                cuerpo_error = json.loads(e.read().decode("utf-8-sig") or "{}")
                detalle = _motivo(cuerpo_error) or cuerpo_error.get("title") or ""
            except Exception:
                pass
            raise TangoError(f"Tango respondió con error HTTP {e.code}" + (f": {detalle}" if detalle else ".")) from None
        except urllib.error.URLError as e:
            raise SinConexion(f"No se pudo conectar con Tango en {self.servidor} ({e.reason}).") from None
        except (TimeoutError, socket.timeout):
            raise SinConexion("Tango tardó demasiado en responder.") from None
        except json.JSONDecodeError:
            raise TangoError("Tango respondió algo que no es JSON.") from None

        if isinstance(datos, dict) and datos.get("succeeded") is False:
            raise TangoError(f"Tango no pudo resolver el pedido: {_motivo(datos) or 'sin detalle'}")
        return datos

    def _get(self, ruta: str, parametros: dict) -> dict:
        return self._pedir("GET", ruta, parametros)

    PAGINAS_EN_PARALELO = 4

    def _paginas(self, ruta: str, parametros: dict) -> Iterator[dict]:
        """Todos los renglones, pidiendo a Tango varias paginas a la vez.

        La primera pagina dice cuantas hay; el resto se pide en paralelo y se
        devuelve en orden.
        """
        def pagina(n: int) -> dict:
            return self._get(ruta, {**parametros, "pageSize": self.TAM_PAGINA, "pageIndex": n})

        primera = pagina(0).get("resultData") or {}
        yield from (primera.get("list") or [])
        total = int(primera.get("totalPages") or 0)
        if total <= 1:
            return
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(self.PAGINAS_EN_PARALELO, total - 1)) as ex:
            for datos in ex.map(pagina, range(1, total)):
                yield from ((datos.get("resultData") or {}).get("list") or [])

    # --------------------------------------------------------------- lecturas
    def listar(self, proceso: int, vista: str = "") -> list[dict]:
        """Todos los registros de un proceso (api/Get), recorriendo las paginas."""
        return list(self._paginas("api/Get", {"process": proceso, "view": vista}))

    def obtener(self, proceso: int, id_registro: int) -> dict | None:
        """Un registro por su ID interno (api/GetById). None si no existe.

        Tango contesta un registro que no existe de dos formas: "value": null, o
        succeeded=false con "Registro inexistente" (visto el 19/11/2026 al
        verificar un borrado). Las dos son None.
        """
        try:
            datos = self._get("api/GetById", {"process": proceso, "id": id_registro})
        except TangoError as e:
            if "registro inexistente" in str(e).lower():
                return None
            raise
        if "value" in datos:
            return datos["value"]
        return datos.get("resultData") or datos

    def consulta_live(self, proceso: int, desde: date | None = None, hasta: date | None = None) -> list[dict]:
        """Todos los renglones de una consulta Live (api/GetApiLiveQueryData)."""
        parametros: dict = {"process": proceso}
        if desde:
            parametros["fromDate"] = desde.strftime("%d/%m/%Y")
        if hasta:
            parametros["toDate"] = hasta.strftime("%d/%m/%Y")
        return list(self._paginas("api/GetApiLiveQueryData", parametros))

    def pdf(self, proceso: int, id_registro: int) -> tuple[str, bytes]:
        """PDF de un comprobante tal como lo imprime Tango (Api/GetPdf). Devuelve (nombre, contenido)."""
        import base64
        datos = self._get("Api/GetPdf", {"process": proceso, "id": id_registro})
        archivo = datos.get("fileResult") or {}
        contenido = archivo.get("fileContents")
        if not contenido:
            raise TangoError("Tango no devolvió el PDF.")
        return (archivo.get("fileDownloadName") or f"{id_registro}.pdf").strip(), base64.b64decode(contenido)

    # --------------------------------------------------------------- escrituras
    # Cambian datos en Tango. Solo las usa el editor de precios.
    def crear(self, proceso: int, registro: dict) -> int:
        """Crea un registro y devuelve su ID."""
        datos = self._pedir("POST", "api/Create", {"process": proceso}, registro)
        return int(datos.get("savedId") or 0)

    def actualizar(self, proceso: int, registro: dict) -> None:
        """Reemplaza un registro (tiene que venir completo, con su ID)."""
        self._pedir("PUT", "api/Update", {"process": proceso}, registro)

    def borrar(self, proceso: int, id_registro: int) -> None:
        self._pedir("DELETE", "api/Delete", {"process": proceso, "id": id_registro})
