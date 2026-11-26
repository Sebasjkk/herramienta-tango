"""
Precios automaticos desde las cotizaciones.

Cuando se emite una cotizacion con un precio MAS ALTO que el de la lista propia del cliente,
ese precio pasa a la lista (es casi seguro el proximo precio). Si el articulo no estaba en la
lista, se agrega con el precio cotizado. Decidido por Sebastian el 26/11/2026:
  - actualiza solo, sin confirmacion (queda en Ver cambios, como cualquier cambio de precio);
  - solo subas: una cotizacion mas barata suele ser un descuento puntual;
  - solo listas propias del cliente (que nadie mas tiene asignada), nunca las generales;
  - si la cotizacion y la lista estan en monedas distintas, no se toca (no se convierte).

Corre solo en la Herramienta del servidor (las de otras PCs no escriben, para no repetir cambios).
Tango no avisa cuando se crea una cotizacion: se revisa cada CADA_SEGUNDOS. La primera vez se
arranca desde la ultima cotizacion que existe, sin tocar el historial.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from . import base_tango, config
from .precios import PedidoInvalido
from .tango import TangoError

log = logging.getLogger(__name__)

CADA_SEGUNDOS = 600
EPS = 0.005
ESTADO_EMITIDA = 2          # GVA08.ESTADO: 2 = Autorizada (emitida)
MAX_HISTORIAL = 60


def _ruta():
    return config.CARPETA / "precios_automaticos.json"


def _corto(numero: str) -> str:
    d = "".join(ch for ch in (numero or "") if ch.isdigit())
    return "BA" + d[-8:].lstrip("0") if d else numero


class PreciosDesdeCotizaciones:
    def __init__(self, servicio_fn, ruta=None):
        self._servicio = servicio_fn            # funcion: devuelve el ServicioTango actual
        self._ruta = ruta or _ruta()
        self._lock = threading.Lock()
        self._parar = threading.Event()

    # ------------------------------------------------------------ estado guardado
    def leer(self) -> dict:
        try:
            return json.loads(self._ruta.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {"desde_id": None, "historial": []}

    def _guardar(self, estado: dict) -> None:
        estado["historial"] = estado.get("historial", [])[-MAX_HISTORIAL:]
        tmp = self._ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._ruta)

    # ------------------------------------------------------------ ciclo
    def iniciar(self) -> None:
        def ciclo():
            self._parar.wait(90)                       # que primero conecte con Tango
            while not self._parar.is_set():
                try:
                    self.revisar()
                except Exception as e:                # nunca tirar abajo el hilo
                    log.warning(f"Precios automáticos: no se pudo revisar ({e})")
                self._parar.wait(CADA_SEGUNDOS)
        threading.Thread(target=ciclo, name="precios-automaticos", daemon=True).start()

    def revisar(self) -> list[dict]:
        """Procesa las cotizaciones nuevas. Devuelve lo que hizo con cada una."""
        with self._lock:
            estado = self.leer()
            if estado.get("desde_id") is None:
                datos = base_tango.cotizaciones_desde(2 ** 31 - 1)       # solo para saber el ID mas alto
                estado["desde_id"] = datos["maximo"]
                estado["inicio"] = datetime.now().isoformat(timespec="seconds")
                self._guardar(estado)
                log.info(f"Precios automáticos: se arranca desde la cotización {datos['maximo']}")
                return []
            datos = base_tango.cotizaciones_desde(estado["desde_id"])
            hechos = []
            for c in datos["cotizaciones"]:
                r = self.procesar(c)
                hechos.append(r)
                estado["desde_id"] = c["id"]
                estado.setdefault("historial", []).append(r)
                self._guardar(estado)
            estado["ultima_revision"] = datetime.now().isoformat(timespec="seconds")
            self._guardar(estado)
            return hechos

    # ------------------------------------------------------------ una cotizacion
    def procesar(self, c: dict) -> dict:
        numero = _corto(c["numero"])
        res = {"cotizacion": numero, "id": c["id"], "cliente": c["codigo_cliente"],
               "fecha": datetime.now().isoformat(timespec="seconds"), "cambios": [], "agregados": [], "omitidos": []}
        if c.get("estado") != ESTADO_EMITIDA:
            res["motivo"] = f"No está emitida (estado {c.get('estado')})."
            return res
        servicio = self._servicio()
        editor = servicio.editor
        try:
            lista = editor._lista(int(c["id_lista"]))
        except (PedidoInvalido, TangoError, TypeError, ValueError):
            res["motivo"] = "No se encontró la lista de precios de la cotización."
            return res
        nombre = (lista.get("NOMBRE_LIS") or "").strip()
        res["lista"] = nombre
        clientes, _ = servicio.clientes()
        con_la_lista = [x for x in clientes if (x.lista_precios or "").strip().upper() == nombre.upper()]
        cliente = next((x for x in clientes if x.codigo.strip().upper() == c["codigo_cliente"].upper()), None)
        if not cliente or [x.codigo for x in con_la_lista] != [cliente.codigo]:
            otros = len([x for x in con_la_lista if not cliente or x.codigo != cliente.codigo])
            res["motivo"] = (f"La lista {nombre} no es propia del cliente"
                             + (f" (la tienen {otros} clientes más)." if otros else " (no la tiene asignada)."))
            return res
        if bool(lista.get("MON_CTE")) != bool(c["en_pesos"]):
            res["motivo"] = f"La cotización está en {'pesos' if c['en_pesos'] else 'dólares'} y la lista {nombre} no: no se convierte."
            return res
        quien = f"Automático: cotización {numero}"
        id_cliente = getattr(cliente, "id", None) or c.get("id_cliente")
        id_lista = int(c["id_lista"])
        renglones = [r for r in editor._todos_los_renglones(forzar=True) if r.get("ID_GVA10") == id_lista]
        vistos = set()
        for r in c["renglones"]:
            cod, precio = r["codigo"], r["precio"]
            if not cod or not precio or precio <= 0 or cod in vistos:
                continue
            vistos.add(cod)
            fila = next((x for x in renglones if (x.get("COD_STA11") or "").strip() == cod), None)
            try:
                if fila is None:
                    editor.agregar_articulo(id_lista, cod, precio, quien, id_cliente, cliente.codigo)
                    res["agregados"].append({"articulo": cod, "precio": precio})
                    continue
                detalle = editor._leer_renglon(fila["ID_GVA17"])
                esp = next((e for e in detalle.get("GVA13") or [] if e.get("ID_GVA14") == id_cliente and (e.get("PRECIO") or 0) > 0), None)
                actual = esp["PRECIO"] if esp else (detalle.get("PRECIO") or 0)
                if precio <= actual + EPS:
                    res["omitidos"].append({"articulo": cod, "precio": precio, "lista": actual,
                                            "motivo": "igual" if abs(precio - actual) <= EPS else "más barato"})
                    continue
                editor.cambiar_precio(fila["ID_GVA17"], precio, quien, id_cliente if esp else None)
                res["cambios"].append({"articulo": cod, "antes": actual, "despues": precio})
            except (PedidoInvalido, TangoError) as e:
                res["omitidos"].append({"articulo": cod, "precio": precio, "motivo": str(e)})
        return res
