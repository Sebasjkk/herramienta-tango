"""
Importar listas de precios desde un Excel.

Formato (el de "Listas_de_precios_69_clientes.xlsx", 19/11/2026):
  - hoja de precios: Lista, Cliente, Artículo, Precio USD, Cargar (SÍ/NO),
    Precio corregido (Fran), Observaciones. Una fila por cliente + artículo.
  - hoja "Listas" (opcional): Nro lista, Descripción, Cliente.

Se respeta el esquema de las listas de cliente que ya hay en Tango: precio de
lista en 0 y el precio real como precio especial del cliente (GVA13). Las listas
nuevas se crean en dólares y se asignan al cliente.

Dos pasos:
  analizar(): lee el Excel y lo compara con Tango; no escribe nada.
  aplicar(): ejecuta el plan en un hilo aparte (son cientos de escrituras) y
             deja el avance en estado(). Es seguro repetirlo: lo que ya esta
             cargado con el mismo precio se saltea.
"""

from __future__ import annotations

import secrets
import threading
import time
import unicodedata

from . import xlsx
from .precios import PROCESO_RENGLONES, MAX_NOMBRE_LISTA, PedidoInvalido
from .tango import TangoError

VIGENCIA_PLAN = 30 * 60
TOLERANCIA = 0.005

CABECERAS_PRECIOS = {
    "lista": ("nro lista", "lista", "numero de lista"),
    "cliente": ("cliente", "codigo cliente"),
    "articulo": ("articulo", "codigo articulo", "codigo"),
    "descripcion": ("descripcion",),
    "precio": ("precio usd", "precio"),
    "cargar": ("cargar",),
    "corregido": ("precio corregido",),
    "observaciones": ("observaciones",),
}
CABECERAS_LISTAS = {"numero": ("nro lista", "lista"), "nombre": ("descripcion", "nombre"), "cliente": ("cliente",)}


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().replace("(", " ").replace(")", " ").split())


def _ubicar(filas: list[list], buscadas: dict, obligatorias: tuple) -> tuple[int, dict] | None:
    """Busca la fila de encabezados (en las primeras 10) y devuelve {campo: columna}."""
    for i, fila in enumerate(filas[:10]):
        nombres = [_norm(c) for c in fila]
        cols = {}
        for campo, opciones in buscadas.items():
            for j, n in enumerate(nombres):
                if n and any(n == o or n.startswith(o + " ") for o in opciones) and j not in cols.values():
                    # "precio" no tiene que agarrar "precio corregido"
                    if campo == "precio" and n.startswith("precio corregido"):
                        continue
                    cols[campo] = j
                    break
        if all(c in cols for c in obligatorias):
            return i, cols
    return None


def _celda(fila: list, col: int | None):
    return fila[col] if col is not None and col < len(fila) else None


def _texto(v) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return "" if v is None else str(v).strip()


def _numero(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    t = str(v).strip().replace("US$", "").replace("$", "").strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


class ImportadorListas:
    def __init__(self, editor, servicio):
        self._editor = editor
        self._servicio = servicio
        self._plan: dict | None = None
        self._estado: dict = {"corriendo": False}
        self._lock = threading.Lock()

    # ============================================================== analizar
    def analizar(self, contenido: bytes) -> dict:
        try:
            hojas = xlsx.leer(contenido)
        except xlsx.ExcelInvalido as e:
            raise PedidoInvalido(str(e)) from None

        hoja_precios = None
        for nombre, filas in hojas.items():
            u = _ubicar(filas, CABECERAS_PRECIOS, ("lista", "cliente", "articulo", "precio"))
            if u:
                hoja_precios = (nombre, filas, *u)
                break
        if not hoja_precios:
            raise PedidoInvalido("No encontré una hoja con las columnas Lista, Cliente, Artículo y Precio.")
        nombres_listas = {}
        for nombre, filas in hojas.items():
            if nombre == hoja_precios[0]:
                continue
            u = _ubicar(filas, CABECERAS_LISTAS, ("numero", "nombre"))
            if u:
                fila0, cols = u
                for f in filas[fila0 + 1:]:
                    n = _numero(_celda(f, cols["numero"]))
                    if n:
                        nombres_listas[int(n)] = _texto(_celda(f, cols["nombre"])).upper()
                break

        # ---- datos de Tango (lecturas)
        articulos = {a.codigo: a for a in self._servicio.articulos(True)[0]}
        clientes = {c.codigo.upper(): c for c in self._servicio.clientes(True)[0]}
        listas_tango = self._editor._listas_crudas()
        por_numero = {x.get("NRO_DE_LIS"): x for x in listas_tango}
        por_nombre = {(x.get("NOMBRE_LIS") or "").strip().upper(): x for x in listas_tango}
        renglones = self._editor._todos_los_renglones(forzar=True)

        # ---- agrupar filas por lista
        _, filas, fila0, cols = hoja_precios
        grupos: dict[int, dict] = {}
        for n, f in enumerate(filas[fila0 + 1:], start=fila0 + 2):
            nro = _numero(_celda(f, cols["lista"]))
            codigo = _texto(_celda(f, cols["articulo"]))
            if not nro and not codigo:
                continue
            if not nro:
                continue
            nro = int(nro)
            g = grupos.setdefault(nro, {"numero": nro, "cliente": _texto(_celda(f, cols["cliente"])).upper(), "filas": []})
            precio = _numero(_celda(f, cols.get("corregido")))
            corregido = precio is not None and precio > 0
            if not corregido:
                precio = _numero(_celda(f, cols["precio"]))
            cargar = _norm(_celda(f, cols.get("cargar")) or "si")
            g["filas"].append({"fila": n, "articulo": codigo, "precio": precio, "corregido": corregido,
                               "descripcion": _texto(_celda(f, cols.get("descripcion"))),
                               "observacion": _texto(_celda(f, cols.get("observaciones"))),
                               "cargar": not cargar.startswith("no")})

        # ---- comparar con Tango
        listas = []
        for nro in sorted(grupos):
            g = grupos[nro]
            nombre = nombres_listas.get(nro) or g["cliente"]
            cli = clientes.get(g["cliente"])
            existente = por_numero.get(nro)
            l = {"numero": nro, "nombre": nombre, "cliente": g["cliente"],
                 "id_cliente": cli.id if cli else None, "razon_social": cli.razon_social if cli else "",
                 "existe": bool(existente), "id_lista": existente.get("ID_GVA10") if existente else None,
                 "error": "", "nota": "", "asignar_de": None, "renglones": []}
            if existente:
                l["nombre"] = (existente.get("NOMBRE_LIS") or "").strip().upper() or nombre
                if nombres_listas.get(nro) and l["nombre"] != nombres_listas[nro]:
                    l["nota"] = f"En el Excel figura como {nombres_listas[nro]}."
                otros = sorted(c.codigo for c in clientes.values()
                               if (c.lista_precios or "").strip().upper() == l["nombre"] and c.codigo != g["cliente"])
                if otros and not any(c.codigo == g["cliente"] for c in clientes.values()
                                     if (c.lista_precios or "").strip().upper() == l["nombre"]):
                    l["error"] = (f"La lista {nro} ({l['nombre']}) la usa {', '.join(otros[:3])} y no {g['cliente']}: "
                                  "revisá el número.")
                elif existente.get("MON_CTE"):
                    l["error"] = "Esa lista está en pesos y los precios del Excel son en dólares."
            else:
                if not nombre:
                    l["error"] = "Falta el nombre de la lista."
                elif len(nombre) > MAX_NOMBRE_LISTA:
                    l["error"] = f"El nombre tiene más de {MAX_NOMBRE_LISTA} letras."
                elif nombre in por_nombre:
                    l["error"] = f"Ya hay otra lista llamada {nombre} (número {por_nombre[nombre].get('NRO_DE_LIS')})."
            if not cli:
                l["error"] = l["error"] or f"El cliente {g['cliente']} no existe en Tango."
            elif (cli.lista_precios or "").strip().upper() != l["nombre"]:
                l["asignar_de"] = cli.lista_precios or "ninguna"

            # renglones que ya estan en la lista: hace falta el detalle para ver el precio especial
            actuales = {}
            if existente:
                ids = {(r.get("COD_STA11") or r.get("COD_ARTICU") or "").strip(): r["ID_GVA17"]
                       for r in renglones if r.get("ID_GVA10") == existente.get("ID_GVA10")}
                pedidos = [ids[f["articulo"]] for f in g["filas"] if f["articulo"] in ids]
                detalles = self._editor._detalles(pedidos) if pedidos else {}
                actuales = {cod: detalles.get(i) for cod, i in ids.items() if i in detalles}
                for cod, i in ids.items():
                    actuales.setdefault(cod, {"ID_GVA17": i, "PRECIO": None, "GVA13": []})

            vistos = set()
            for f in g["filas"]:
                r = {**f, "estado": "agregar", "actual": None, "id_renglon": None, "motivo": ""}
                art = articulos.get(f["articulo"])
                if not f["cargar"]:
                    r.update(estado="no_cargar", motivo="Marcado para no cargar.")
                elif not art:
                    r.update(estado="error", motivo="No existe ese artículo en Tango.")
                elif f["precio"] is None or f["precio"] <= 0:
                    r.update(estado="error", motivo="Sin precio.")
                elif f["articulo"] in vistos:
                    r.update(estado="error", motivo="Está dos veces en esta lista.")
                elif f["articulo"] in actuales:
                    d = actuales[f["articulo"]]
                    esp = next((c for c in d.get("GVA13") or [] if c.get("ID_GVA14") == l["id_cliente"]), None)
                    actual = esp.get("PRECIO") if esp else d.get("PRECIO")
                    r["actual"], r["id_renglon"] = actual, d.get("ID_GVA17")
                    igual = actual is not None and abs(actual - round(f["precio"], 2)) < TOLERANCIA
                    r["estado"] = "igual" if igual and esp else "distinto"
                if f["precio"] is not None:
                    r["precio"] = round(f["precio"], 2)
                if art:
                    r["descripcion"] = r["descripcion"] or art.descripcion
                vistos.add(f["articulo"])
                l["renglones"].append(r)
            listas.append(l)

        plan = {"id": secrets.token_hex(6), "creado": time.time(), "listas": listas, "resumen": self._resumen(listas)}
        with self._lock:
            self._plan = plan
        return plan

    @staticmethod
    def _resumen(listas: list[dict]) -> dict:
        rs = [r for l in listas if not l["error"] for r in l["renglones"]]
        cuenta = lambda e: sum(1 for r in rs if r["estado"] == e)
        return {
            "listas": len(listas),
            "listas_nuevas": sum(1 for l in listas if not l["existe"] and not l["error"]),
            "listas_existentes": sum(1 for l in listas if l["existe"] and not l["error"]),
            "listas_con_error": sum(1 for l in listas if l["error"]),
            "asignaciones": sum(1 for l in listas if l["asignar_de"] and not l["error"]),
            "agregar": cuenta("agregar"), "igual": cuenta("igual"), "distinto": cuenta("distinto"),
            "error": cuenta("error"), "no_cargar": cuenta("no_cargar"),
            "con_observaciones": sum(1 for r in rs if r["observacion"] and r["estado"] in ("agregar", "distinto")),
        }

    # ============================================================== aplicar
    def estado(self) -> dict:
        with self._lock:
            return dict(self._estado)

    def aplicar(self, id_plan: str, quien: str, actualizar_distintos: bool, saltear_observaciones: bool) -> dict:
        with self._lock:
            if self._estado.get("corriendo"):
                raise PedidoInvalido("Ya hay una importación en curso.")
            plan = self._plan
            if not plan or plan["id"] != id_plan or time.time() - plan["creado"] > VIGENCIA_PLAN:
                raise PedidoInvalido("La vista previa venció o cambió: volvé a cargar el Excel.")
            pasos = self._pasos(plan, actualizar_distintos, saltear_observaciones)
            if not pasos:
                raise PedidoInvalido("No hay nada para cargar.")
            self._plan = None          # un plan se aplica una sola vez
            self._estado = {"corriendo": True, "total": len(pasos), "hechos": 0, "actual": "", "errores": [],
                            "inicio": time.time(), "fin": None, "quien": quien}
        threading.Thread(target=self._correr, args=(pasos, quien), daemon=True).start()
        return self.estado()

    @staticmethod
    def _pasos(plan: dict, actualizar_distintos: bool, saltear_observaciones: bool) -> list[tuple]:
        pasos = []
        for l in plan["listas"]:
            if l["error"]:
                continue
            elegidos = [r for r in l["renglones"]
                        if (r["estado"] == "agregar" or (r["estado"] == "distinto" and actualizar_distintos))
                        and not (saltear_observaciones and r["observacion"])]
            if not l["existe"]:
                if not elegidos:
                    continue
                pasos.append(("crear", l, None))
            if l["asignar_de"] and (elegidos or l["existe"]):
                pasos.append(("asignar", l, None))
            pasos += [("renglon", l, r) for r in elegidos]
        return pasos

    def _correr(self, pasos: list[tuple], quien: str) -> None:
        editor = self._editor
        listas_por_numero: dict[int, dict] = {}
        articulos = {a.codigo: a for a in self._servicio.articulos()[0]}
        fallo_lista: set[int] = set()
        for tipo, l, r in pasos:
            nro = l["numero"]
            texto = {"crear": f"Creando la lista {l['nombre']}",
                     "asignar": f"Asignando {l['nombre']} a {l['razon_social'] or l['cliente']}",
                     "renglon": f"{l['nombre']}: {r['articulo'] if r else ''}"}[tipo]
            with self._lock:
                self._estado["actual"] = texto
            try:
                if nro in fallo_lista:
                    raise PedidoInvalido("No se pudo crear la lista.")
                if tipo == "crear":
                    creada = editor.crear_lista(l["nombre"], "US$", quien, nro)
                    l["id_lista"] = creada["id"]
                elif tipo == "asignar":
                    editor.asignar_lista(l["id_lista"], l["id_cliente"], quien)
                else:
                    with editor._lock:
                        if nro not in listas_por_numero:
                            listas_por_numero[nro] = editor._lista(l["id_lista"])
                        lista = listas_por_numero[nro]
                        if r["estado"] == "distinto" and r["id_renglon"]:
                            self._poner_especial(r["id_renglon"], l["id_cliente"], l["cliente"], r["precio"], quien, lista)
                        else:
                            editor._crear_renglon(lista, articulos[r["articulo"]], r["precio"], quien,
                                                  l["id_cliente"], l["cliente"])
            except (PedidoInvalido, TangoError, KeyError) as e:
                if tipo == "crear":
                    fallo_lista.add(nro)
                with self._lock:
                    self._estado["errores"].append({"lista": l["nombre"], "articulo": r["articulo"] if r else "",
                                                    "error": str(e)})
            with self._lock:
                self._estado["hechos"] += 1
        editor._invalidar()
        self._servicio.olvidar("clientes")
        with self._lock:
            self._estado.update(corriendo=False, fin=time.time(), actual="")

    def _poner_especial(self, id_renglon: int, id_cliente: int, codigo_cliente: str, precio: float,
                        quien: str, lista: dict) -> None:
        """Pone (o agrega) el precio especial del cliente en un renglon que ya existe."""
        editor = self._editor
        actual = editor._leer_renglon(id_renglon)
        especiales = [dict(c) for c in actual.get("GVA13") or []]
        suyo = [c for c in especiales if c.get("ID_GVA14") == id_cliente]
        if suyo:
            for c in suyo:
                c["PRECIO"] = precio
        else:
            especiales.append({
                "ACTUALIZAR_CONTROL_PRECIOS": False, "ID_GVA10": actual["ID_GVA10"], "ID_STA11": actual.get("ID_STA11"),
                "ID_GVA14": id_cliente, "FILLER": "", "COD_ARTICU": actual.get("COD_ARTICU"), "COD_CLIENT": codigo_cliente,
                "NRO_LISTA": lista.get("NRO_DE_LIS"), "PRECIO": precio, "ID_GVA17": id_renglon})
        editor._c.actualizar(PROCESO_RENGLONES, {**actual, "GVA13": especiales})
        despues = editor._leer_renglon(id_renglon)
        editor.registro.anotar(quien, "cambiar precio", lista=lista.get("NOMBRE_LIS"), articulo=actual.get("COD_ARTICU"),
                               cliente=id_cliente, antes={"especiales": [c.get("PRECIO") for c in suyo] or None},
                               despues={"precio": precio}, origen="importación")
        if not any(c.get("ID_GVA14") == id_cliente and c.get("PRECIO") == precio for c in despues.get("GVA13") or []):
            raise TangoError(f"El precio de {actual.get('COD_ARTICU')} no quedó guardado. Revisalo en Tango.")
