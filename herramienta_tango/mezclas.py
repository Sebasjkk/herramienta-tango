"""
Mezclas de polvos.

Una mezcla se cotiza y se remite como un articulo generico; los polvos que se
usaron tienen que salir del stock, cada uno de su partida. Tango no deja crear
egresos de a uno por la API (los procesos 20214 y 20306 responden 401, probado el
19/11/2026), asi que la Herramienta:

  1. guarda la mezcla (polvos, partidas, kilos, remito o cliente) en mezclas.json;
  2. arma la planilla de "Egresos de Stock" con esos renglones, escribiendo sobre
     la plantilla original que baja Tango (tiene una hoja oculta _metadata que
     valida el archivo y se rompe si se regenera);
  3. alguien la importa en Tango (Egresos de Stock > Registrar egreso de Stock) y
     marca la mezcla como subida.

Valores de la plantilla probados con los ajustes masivos: depósito " 1" (con un
espacio adelante), "Informar partida" = "Si" y la unidad con su sigla (UNI, KG).
"""

from __future__ import annotations

import io
import json
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from . import config
from .precios import PedidoInvalido
from .tango import TangoError

PLANTILLA = Path(__file__).resolve().parent / "plantillas" / "egreso_stock.xlsx"
HOJA_RENGLONES = "xl/worksheets/sheet2.xml"     # "Artículos y partidas"
MAX_RENGLONES = 20
MAX_REFERENCIA = 60


def ruta_registro() -> Path:
    return config.CARPETA / "mezclas.json"


def _codigo_deposito(codigo: str) -> str:
    """Tango espera el codigo de deposito como lo guarda: " 1" (dos caracteres)."""
    return (codigo or "1").strip().rjust(2)


class RegistroMezclas:
    """Historial de mezclas en un archivo JSON de la carpeta del programa."""

    def __init__(self, ruta: Path):
        self.ruta = ruta
        self._lock = threading.Lock()

    def _leer(self) -> list[dict]:
        try:
            return json.loads(self.ruta.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []

    def _guardar(self, datos: list[dict]) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.ruta)

    def todas(self) -> list[dict]:
        with self._lock:
            return sorted(self._leer(), key=lambda m: m["id"], reverse=True)

    def agregar(self, mezcla: dict) -> dict:
        with self._lock:
            datos = self._leer()
            mezcla = {**mezcla, "id": max([m["id"] for m in datos] + [0]) + 1}
            datos.append(mezcla)
            self._guardar(datos)
            return mezcla

    def cambiar(self, ids: list[int], cambio) -> list[dict]:
        """Aplica cambio(mezcla) a las mezclas pedidas; devuelve las que cambiaron."""
        with self._lock:
            datos = self._leer()
            tocadas = [m for m in datos if m["id"] in ids]
            if len(tocadas) != len(set(ids)):
                raise PedidoInvalido("Alguna de esas mezclas ya no existe.")
            for m in tocadas:
                cambio(m)
            self._guardar([m for m in datos if not m.get("_borrar")])
            return tocadas


class EditorMezclas:
    def __init__(self, servicio, registro: RegistroMezclas | None = None):
        self._servicio = servicio
        self.registro = registro or RegistroMezclas(ruta_registro())

    # -------------------------------------------------------------- alta
    def crear(self, referencia: str, renglones: list, quien: str) -> dict:
        referencia = " ".join(str(referencia or "").split())[:MAX_REFERENCIA]
        if not referencia:
            raise PedidoInvalido("Escribí el remito o el cliente de la mezcla.")
        if not isinstance(renglones, list) or not renglones:
            raise PedidoInvalido("Agregá los productos que usaste.")
        if len(renglones) > MAX_RENGLONES:
            raise PedidoInvalido(f"Una mezcla puede tener hasta {MAX_RENGLONES} productos.")

        articulos = {a.codigo: a for a in self._servicio.articulos()[0]}
        saldos = self._servicio.saldos_por_partida()[0]
        try:
            codigos_dep = {d.nombre.strip().upper(): d.codigo for d in self._servicio.depositos()[0]}
        except TangoError:
            codigos_dep = {}

        salida, vistos = [], set()
        for i, r in enumerate(renglones, 1):
            if not isinstance(r, dict):
                raise PedidoInvalido("Pedido inválido.")
            codigo = str(r.get("articulo") or "").strip()
            art = articulos.get(codigo)
            if not art:
                raise PedidoInvalido(f"Producto {i}: elegí un artículo de la lista.")
            try:
                cantidad = round(float(str(r.get("cantidad")).replace(",", ".")), 4)
            except (ValueError, TypeError):
                raise PedidoInvalido(f"Producto {i} ({codigo}): la cantidad no es un número.") from None
            if not 0 < cantidad < 1e7:
                raise PedidoInvalido(f"Producto {i} ({codigo}): poné una cantidad mayor que cero.")
            partida = str(r.get("partida") or "").strip()
            deposito, deposito_nombre, saldo = " 1", "CENTRAL", None
            if art.usa_partidas:
                if not partida:
                    raise PedidoInvalido(f"Producto {i} ({codigo}): elegí la partida de la que salió.")
                filas = [s for s in saldos if s.codigo_articulo == codigo and s.partida == partida]
                if not filas:
                    # Tango solo acepta salidas de partidas que existen en ese articulo y deposito
                    raise PedidoInvalido(f"Producto {i} ({codigo}): la partida {partida} no figura en Tango para ese artículo.")
                fila = max(filas, key=lambda s: s.saldo)
                deposito_nombre = fila.deposito.strip().upper() or "CENTRAL"
                deposito = _codigo_deposito(codigos_dep.get(deposito_nombre, "1"))
                saldo = fila.saldo
            else:
                partida = ""
            clave = (codigo, partida)
            if clave in vistos:
                raise PedidoInvalido(f"{codigo}{' partida ' + partida if partida else ''} está dos veces: sumá los kilos en un solo renglón.")
            vistos.add(clave)
            salida.append({"codigo": codigo, "descripcion": art.descripcion, "partida": partida,
                           "deposito": deposito, "deposito_nombre": deposito_nombre,
                           "unidad": art.unidad or (fila.unidad if art.usa_partidas else ""),
                           "cantidad": cantidad, "saldo_antes": saldo})

        mezcla = {"fecha": datetime.now().isoformat(timespec="seconds"), "quien": quien,
                  "referencia": referencia, "renglones": salida, "estado": "pendiente"}
        return self.registro.agregar(mezcla)

    # -------------------------------------------------------------- estado
    def marcar_subidas(self, ids: list[int], quien: str) -> list[dict]:
        ahora = datetime.now().isoformat(timespec="seconds")
        def subir(m):
            if m["estado"] != "subida":
                m.update(estado="subida", subida_por=quien, subida_fecha=ahora)
        return self.registro.cambiar(ids, subir)

    def borrar(self, id_mezcla: int, quien: str) -> None:
        def borrar(m):
            if m["estado"] == "subida":
                raise PedidoInvalido("Esa mezcla ya se subió a Tango: no se puede borrar desde acá.")
            m["_borrar"] = True
        self.registro.cambiar([id_mezcla], borrar)

    # -------------------------------------------------------------- planilla
    def planilla(self, ids: list[int]) -> tuple[str, bytes]:
        todas = {m["id"]: m for m in self.registro.todas()}
        elegidas = [todas[i] for i in ids if i in todas]
        if not elegidas:
            raise PedidoInvalido("Elegí al menos una mezcla.")
        renglones = [r for m in elegidas for r in m["renglones"]]
        nombre = "Egreso_mezcla_" + "-".join(str(m["id"]) for m in sorted(elegidas, key=lambda m: m["id"])) + ".xlsx"
        return nombre, armar_planilla(renglones)


# ------------------------------------------------------------------ xlsx
def _celda_texto(ref: str, texto: str) -> str:
    return f'<c r="{ref}" s="4" t="inlineStr"><is><t xml:space="preserve">{escape(texto)}</t></is></c>'


def _celda_numero(ref: str, numero: float) -> str:
    texto = f"{numero:.4f}".rstrip("0").rstrip(".")
    return f'<c r="{ref}" s="5"><v>{texto}</v></c>'


def armar_planilla(renglones: list[dict], plantilla: Path = PLANTILLA) -> bytes:
    """Copia la plantilla de Tango tal cual y agrega los renglones en la hoja visible.

    Solo se reescribe sheet2.xml; el resto del archivo (hojas ocultas, metadata,
    estilos, textos compartidos) se copia byte a byte.
    """
    filas = []
    for n, r in enumerate(renglones, start=2):
        celdas = [
            _celda_texto(f"A{n}", r["codigo"]),
            _celda_texto(f"B{n}", r.get("descripcion", "")),
            _celda_texto(f"C{n}", r.get("deposito") or " 1"),
            _celda_texto(f"D{n}", "Si" if r.get("partida") else "No"),
        ]
        if r.get("partida"):
            celdas.append(_celda_texto(f"E{n}", r["partida"]))
        if r.get("unidad"):
            celdas.append(_celda_texto(f"F{n}", r["unidad"]))
        celdas.append(_celda_numero(f"G{n}", float(r["cantidad"])))
        filas.append(f'<row r="{n}">{"".join(celdas)}</row>')

    salida = io.BytesIO()
    with zipfile.ZipFile(plantilla) as origen, zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as destino:
        for info in origen.infolist():
            contenido = origen.read(info.filename)
            if info.filename == HOJA_RENGLONES:
                xml = contenido.decode("utf-8")
                if "</row></sheetData>" not in xml:
                    raise TangoError("La plantilla de egresos no tiene la forma esperada.")
                ultima = len(renglones) + 1
                xml = xml.replace('<dimension ref="A1"/>', f'<dimension ref="A1:K{ultima}"/>', 1)
                xml = xml.replace("</row></sheetData>", "</row>" + "".join(filas) + "</sheetData>", 1)
                contenido = xml.encode("utf-8")
            destino.writestr(info, contenido)
    return salida.getvalue()
