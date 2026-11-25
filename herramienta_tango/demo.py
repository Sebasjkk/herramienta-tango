"""
Modo demo: la Herramienta con datos inventados, sin Tango ni base de datos.

Sirve para ver y probar las pantallas en cualquier PC:

    python HerramientaTango.pyw --demo

Usa el puerto 8086 (no choca con la Herramienta real) y no guarda nada en
config.ini ni en token.dat. Los cambios (precios, etc.) quedan en memoria y se
pierden al cerrar. Las consultas a la base SQL de Tango (movimientos,
importaciones, valorizacion) avisan que no estan disponibles en la demo.
"""

from __future__ import annotations

import random
import threading
from datetime import date, timedelta

from .tango import procesos
from .tango.cliente import TangoError

PUERTO_DEMO = 8086

_FAMILIAS = [
    ("PZ", "POLVO ZINC", "KG"), ("PA", "POLVO ALUMINIO", "KG"), ("PN", "POLVO NIQUEL CROMO", "KG"),
    ("PC", "POLVO CARBURO TUNGSTENO", "KG"), ("PO", "POLVO OXIDO CROMO", "KG"), ("AL", "ALAMBRE ZINC", "KG"),
    ("AA", "ALAMBRE ALUMINIO", "KG"), ("BO", "BOQUILLA PISTOLA", "UN"), ("EL", "ELECTRODO", "UN"),
    ("GR", "GRANALLA OXIDO ALUMINIO", "KG"),
]
_VARIANTES = ["", " FINO", " 45-90 UM", " 15-45 UM", " 1.6 MM", " 3.2 MM"]
_CLIENTES = [
    "METALURGICA DEL SUR SA", "TALLERES ANDINOS SRL", "RECUBRIMIENTOS DEL LITORAL SA", "INDUSTRIAS PAMPA SA",
    "MANTENIMIENTO NORTE SRL", "ACEROS PATAGONICOS SA", "TERMOMETALIZADOS CUYO SRL", "NAVAL RIO DE LA PLATA SA",
    "PETROSERVICIOS CENTRO SA", "AGRO REPUESTOS OESTE SRL", "PAPELERA DEL PARANA SA", "MINERA PUNA SA",
    "HIDRAULICA MODERNA SRL", "ENERGIA COSTERA SA", "FUNDICION LOS ALAMOS SRL", "TALLER EL TORNO",
]
_VENDEDORES = ["Gómez", "Fernández", "Ruiz"]
_DEPOSITOS = [(1, "01", "CENTRAL"), (2, "02", "TALLER"), (3, "03", "EN TRANSITO")]
_LISTAS = [(1, 1, "MAYORISTA", True), (2, 2, "MINORISTA", True), (3, 3, "DOLARES", False), (4, 10, "METALURGICA DEL SUR", True)]


def _f(d: date) -> str:
    return d.isoformat() + "T00:00:00"


class ClienteDemo:
    """Hace de ClienteTango con datos inventados (siempre los mismos)."""

    def __init__(self, *args, **kwargs):
        r = random.Random(42)
        hoy = date.today()
        self._lock = threading.Lock()
        self.servidor = "demo"

        self.articulos = []
        n = 0
        for fam, nombre, um in _FAMILIAS:
            for var in r.sample(_VARIANTES, 4):
                n += 1
                self.articulos.append({
                    "ID_STA11": n, "COD_STA11": f"{fam}{n:04d}", "DESCRIPCIO": (nombre + var).strip(),
                    "DESC_ADIC": "", "SINONIMO": "", "COD_BARRA": f"779{n:010d}",
                    "USA_PARTID": um == "KG", "STOCK": True, "PERFIL": "A", "MEDIDA_STOCK_SIGLA": um,
                    "COD_NCM": "7903.10.00", "STOCK_MINI": 10, "STOCK_MAXI": 500,
                    "PTO_PEDIDO": r.choice([0, 20, 50, 100]),
                })
        self.depositos = [{"ID_STA22": i, "COD_STA22": c, "NOMBRE_SUC": nom, "DIR_SUCURS": "", "INHABILITA": False}
                          for i, c, nom in _DEPOSITOS]
        self.listas = [{"ID_GVA10": i, "NRO_DE_LIS": nro, "NOMBRE_LIS": nom, "HABILITADA": True,
                        "INCLUY_IVA": False, "MON_CTE": pesos} for i, nro, nom, pesos in _LISTAS]
        self.clientes = []
        for i, razon in enumerate(_CLIENTES, 1):
            lista = _LISTAS[3] if i == 1 else r.choice(_LISTAS[:3])
            self.clientes.append({
                "ID_GVA14": i, "COD_GVA14": f"{i:06d}", "RAZON_SOCI": razon,
                "CUIT": f"30-{r.randint(10000000, 79999999)}-{r.randint(0, 9)}", "HABILITADO": True,
                "GVA10_NOMBRE_LIS": lista[2], "ID_GVA10": lista[0],
                "DOMICILIO": f"Av. Industrial {r.randint(100, 4000)}", "LOCALIDAD": r.choice(["Rosario", "Córdoba", "Avellaneda", "Neuquén", "Mendoza"]),
                "C_POSTAL": str(r.randint(1000, 9000)), "COD_PROVIN": "01", "TELEFONO_1": f"011 4{r.randint(100, 999)}-{r.randint(1000, 9999)}",
                "DIRECCION_ENTREGA": [], "CONTACTOS": [],
            })

        # saldos: por partida para los que llevan partidas, por articulo para todos
        self.partidas, self.saldos_art = [], []
        id_partida = 0
        for a in self.articulos:
            total = 0.0
            for dep in r.sample(_DEPOSITOS[:2], r.choice([1, 1, 2])):
                if a["USA_PARTID"]:
                    for _ in range(r.choice([1, 2, 3])):
                        id_partida += 1
                        saldo = round(r.choice([0, r.uniform(-5, 0), r.uniform(1, 300)]), 2) if r.random() < .9 else 0
                        total += saldo
                        self.partidas.append({
                            "ID_STA08": id_partida, "COD_ARTICULO": a["COD_STA11"], "DESCRIPCION": a["DESCRIPCIO"],
                            "DESCRIPCION_DEPOSITO": dep[2], "PARTIDA": str(700 + id_partida),
                            "NUMERO_DE_DESPACHO": f"26001IC04{r.randint(100000, 999999)}X",
                            "FECHA_DE_VENCIMIENTO": _f(hoy + timedelta(days=r.randint(-30, 900))),
                            "UM_CONTROL_STOCK": a["MEDIDA_STOCK_SIGLA"], "SALDO_CONTROL_STOCK": saldo,
                        })
                else:
                    total = float(r.randint(-2, 60))
                self.saldos_art.append({
                    "ID_STA11": a["ID_STA11"], "COD_ARTICULO": a["COD_STA11"], "DESCRIPCION": a["DESCRIPCIO"],
                    "DESCRIPCION_DEPOSITO": dep[2], "UM_CONTROL_STOCK": a["MEDIDA_STOCK_SIGLA"],
                    "SALDO_CONTROL_STOCK": round(total, 2), "CANTIDAD_COMPROMETIDA_CONTROL_STOCK": r.choice([0, 0, 5, 20]),
                    "CANTIDAD_A_RECIBIR_CONTROL_STOCK": r.choice([0, 0, 0, 100]),
                })

        # precios: renglones de GVA17 por lista
        self.renglones_precio = {}
        id_r = 0
        self.base_precio = {a["ID_STA11"]: round(r.uniform(5, 400), 2) for a in self.articulos}
        for lst in self.listas:
            for a in self.articulos:
                id_r += 1
                p = self.base_precio[a["ID_STA11"]] * {1: 1.0, 2: 1.3, 3: 0.001, 4: 0}[lst["ID_GVA10"]]
                if lst["ID_GVA10"] == 3:
                    p = round(self.base_precio[a["ID_STA11"]] / 10, 2)
                especiales = []
                if lst["ID_GVA10"] == 4:
                    especiales = [{"ID_GVA13": id_r, "ID_GVA14": 1, "COD_CLIENT": "000001",
                                   "PRECIO": round(self.base_precio[a["ID_STA11"]] * .9, 2)}]
                self.renglones_precio[id_r] = {
                    "ID_GVA17": id_r, "ID_GVA10": lst["ID_GVA10"], "NRO_DE_LIS": lst["NRO_DE_LIS"],
                    "ID_STA11": a["ID_STA11"], "COD_STA11": a["COD_STA11"], "DESCRIPCIO": a["DESCRIPCIO"],
                    "PRECIO": round(p, 2), "FECHA_MODI": _f(hoy - timedelta(days=r.randint(0, 120))), "GVA13": especiales,
                }

        # pedidos
        self.pedidos = {}
        for i in range(1, 41):
            cli = r.choice(self.clientes)
            lst = next(l for l in self.listas if l["ID_GVA10"] == cli["ID_GVA10"])
            fecha = hoy - timedelta(days=r.randint(0, 90))
            renglones = []
            for a in r.sample(self.articulos, r.randint(1, 5)):
                cant = float(r.choice([5, 10, 25, 50, 100]))
                falta = r.choice([cant, cant, 0, round(cant / 2)])
                precio = self.base_precio[a["ID_STA11"]]
                renglones.append({"COD_ARTICULO": a["COD_STA11"], "DESCRIPCION_ARTICULO": a["DESCRIPCIO"],
                                  "CANTIDAD_PEDIDA": cant, "CANTIDAD_A_DESCARGAR": falta,
                                  "CANTIDAD_PENDIENTE_A_FACTURAR": falta, "PRECIO": precio,
                                  "PORCENTAJE_BONIFICACION": 0, "IMPORTE": round(cant * precio, 2)})
            estado = 2 if any(x["CANTIDAD_A_DESCARGAR"] for x in renglones) else 4
            self.pedidos[i] = {
                "ID_GVA21": i, "NRO_PEDIDO": f"00001{i + 2000:08d}", "ID_GVA14": cli["ID_GVA14"],
                "CODIGO_CLIENTE": cli["COD_GVA14"], "RAZON_SOCIAL_CLIENTE": cli["RAZON_SOCI"],
                "FECHA_PEDI": _f(fecha), "FECHA_PEDIDO": _f(fecha), "FECHA_ENTR": _f(fecha + timedelta(days=15)),
                "FECHA_ENTREGA": _f(fecha + timedelta(days=15)), "ESTADO": estado,
                "NRO_OC_COMP": f"OC-{r.randint(1000, 9999)}", "NRO_ORDEN_COMPRA": "", "FECHA_O_COMP": _f(fecha),
                "NOMBRE_SUC": "CENTRAL", "NOMBRE_LIS": lst["NOMBRE_LIS"], "ID_GVA10": lst["ID_GVA10"],
                "TOTAL_PEDI": round(sum(x["IMPORTE"] for x in renglones), 2), "N_REMITO": "",
                "ID_MONEDA": 1, "COTIZACION": 1, "COMPROMETE_STOCK": True, "RENGLON_DTO": renglones,
                "NOTA_PEDIDO_DTO": [], "LEYENDA_1": "", "OBSERVACIONES": "",
            }
            self.pedidos[i]["NRO_ORDEN_COMPRA"] = self.pedidos[i]["NRO_OC_COMP"]

        # cotizaciones y sus renglones
        self.cotizaciones, self.renglones_cot = [], []
        for i in range(1, 31):
            cli = r.choice(self.clientes)
            fecha = hoy - timedelta(days=r.randint(0, 60))
            numero = f"00001{3200 + i:08d}"
            self.cotizaciones.append({
                "ID_GVA08": i, "TALONARIO": 1, "NRO_COTIZACION": numero, "FECHA": _f(fecha),
                "FECHA_DE_VIGENCIA": _f(fecha + timedelta(days=r.choice([7, 15, 30]))),
                "COD_CLIENTE": cli["COD_GVA14"], "RAZON_SOCIAL": cli["RAZON_SOCI"],
                "VENDEDOR": r.choice(_VENDEDORES), "ESTADO": r.choice([2, 2, 2, 4, 5]),
                "MONEDA": r.random() < .7, "PERDIDA": False,
            })
            for a in r.sample(self.articulos, r.randint(1, 4)):
                self.renglones_cot.append({"NRO_COTIZACION": numero, "COD_ARTICULO": a["COD_STA11"],
                                           "DESCRIPCION": a["DESCRIPCIO"], "CANTIDAD": r.choice([5, 10, 50]),
                                           "PRECIO": self.base_precio[a["ID_STA11"]], "PORC_DESCUENTO": 0})

        # comprobantes de venta (facturas y remitos) y renglones de venta
        self.comprobantes, self.ventas = [], []
        for i in range(1, 121):
            cli = r.choice(self.clientes)
            fecha = hoy - timedelta(days=r.randint(0, 365))
            tipo = r.choice(["FAC", "FAC", "REM"])
            numero = f"{'R' if tipo == 'REM' else 'A'}00008{i + 100:08d}"
            self.comprobantes.append({"ID_STA14": i, "TIPO_COMPROBANTE": tipo, "NRO_COMPROBANTE": numero,
                                      "FECHA": _f(fecha), "ID_GVA14": cli["ID_GVA14"],
                                      "COD_CLIENTE": cli["COD_GVA14"], "RAZON_SOCIAL": cli["RAZON_SOCI"], "ESTADO": "Normal"})
            if tipo == "FAC":
                for a in r.sample(self.articulos, r.randint(1, 3)):
                    cant = float(r.choice([5, 10, 25]))
                    self.ventas.append({"FECHA_DE_EMISION": _f(fecha), "TIPO_COMPROBANTE": "FAC", "NRO_COMPROBANTE": numero,
                                        "RAZON_SOCIAL": cli["RAZON_SOCI"], "NOMBRE_VENDEDOR": r.choice(_VENDEDORES),
                                        "COD_ARTICULO": a["COD_STA11"], "DESCRIPCION": a["DESCRIPCIO"],
                                        "CANTIDAD": cant, "TOTAL": round(cant * self.base_precio[a["ID_STA11"]], 2)})
        self._siguiente_id = 100000

    # ------------------------------------------------------------ lecturas
    def _precios_vigentes(self) -> list[dict]:
        listas = {l["ID_GVA10"]: l for l in self.listas}
        filas = []
        for x in self.renglones_precio.values():
            l = listas.get(x["ID_GVA10"]) or {}
            base = {"COD_ARTICULO": x["COD_STA11"], "DESCRIPCION": x["DESCRIPCIO"], "NRO_LISTA_DE_PRECIOS": x["NRO_DE_LIS"],
                    "DESC_LISTA_DE_PRECIOS": l.get("NOMBRE_LIS", ""), "MONEDA": l.get("MON_CTE", True),
                    "FECHA_MODIFICACION": x["FECHA_MODI"]}
            if x["PRECIO"]:
                filas.append({**base, "PRECIO": x["PRECIO"]})
            for e in x.get("GVA13") or []:
                cli = next((c for c in self.clientes if c["ID_GVA14"] == e["ID_GVA14"]), {})
                filas.append({**base, "PRECIO": e["PRECIO"], "COD_CLIENTE": cli.get("COD_GVA14", ""),
                              "RAZON_SOCIAL": cli.get("RAZON_SOCI", "")})
        return filas

    def listar(self, proceso: int, vista: str = "") -> list[dict]:
        with self._lock:
            datos = {
                procesos.ARTICULOS: self.articulos, procesos.DEPOSITOS: self.depositos,
                procesos.CLIENTES: self.clientes, procesos.PEDIDOS: list(self.pedidos.values()),
                procesos.LISTAS_PRECIOS: self.listas, procesos.PRECIOS_ABM: list(self.renglones_precio.values()),
            }.get(proceso, [])
            return [dict(x) for x in datos]

    def obtener(self, proceso: int, id_registro: int) -> dict | None:
        with self._lock:
            if proceso == procesos.PEDIDOS:
                x = self.pedidos.get(int(id_registro))
            elif proceso == procesos.PRECIOS_ABM:
                x = self.renglones_precio.get(int(id_registro))
            else:
                fuente = {procesos.CLIENTES: (self.clientes, "ID_GVA14"), procesos.LISTAS_PRECIOS: (self.listas, "ID_GVA10"),
                          procesos.ARTICULOS: (self.articulos, "ID_STA11"), procesos.DEPOSITOS: (self.depositos, "ID_STA22")}.get(proceso)
                x = next((r for r in fuente[0] if r[fuente[1]] == int(id_registro)), None) if fuente else None
            return _copia(x) if x else None

    def consulta_live(self, proceso: int, desde: date | None = None, hasta: date | None = None) -> list[dict]:
        if proceso == procesos.LIVE_PRECIOS_VIGENTES:
            with self._lock:
                return self._precios_vigentes()
        filas = {
            procesos.LIVE_SALDOS_POR_PARTIDA: self.partidas, procesos.LIVE_SALDOS_POR_ARTICULO: self.saldos_art,
            procesos.LIVE_COTIZACIONES: self.cotizaciones, procesos.LIVE_COTIZACIONES_DETALLE: self.renglones_cot,
            procesos.LIVE_COMPROBANTES_VENTA: self.comprobantes, procesos.LIVE_VENTAS_DETALLE: self.ventas,
        }.get(proceso, [])
        if desde or hasta:
            def en_rango(x):
                f = (x.get("FECHA") or x.get("FECHA_DE_EMISION") or "")[:10]
                return not f or ((not desde or f >= desde.isoformat()) and (not hasta or f <= hasta.isoformat()))
            filas = [x for x in filas if en_rango(x)]
        return [dict(x) for x in filas]

    def pdf(self, proceso: int, id_registro: int) -> tuple[str, bytes]:
        raise TangoError("En el modo demo no hay PDF de Tango.")

    # ------------------------------------------------------------ escrituras (en memoria)
    def _tabla(self, proceso: int):
        if proceso == procesos.PRECIOS_ABM:
            return self.renglones_precio, "ID_GVA17"
        if proceso == procesos.LISTAS_PRECIOS:
            return None, "ID_GVA10"
        if proceso == procesos.PEDIDOS:
            return self.pedidos, "ID_GVA21"
        raise TangoError("El modo demo no permite modificar esto.")

    def crear(self, proceso: int, registro: dict) -> int:
        with self._lock:
            tabla, clave = self._tabla(proceso)
            self._siguiente_id += 1
            nuevo = {**_copia(registro), clave: self._siguiente_id}
            if tabla is None:
                self.listas.append(nuevo)
            else:
                tabla[self._siguiente_id] = nuevo
            return self._siguiente_id

    def actualizar(self, proceso: int, registro: dict) -> None:
        with self._lock:
            tabla, clave = self._tabla(proceso)
            id_ = int(registro[clave])
            if tabla is None:
                self.listas = [_copia(registro) if l[clave] == id_ else l for l in self.listas]
            elif id_ in tabla:
                tabla[id_] = _copia(registro)

    def borrar(self, proceso: int, id_registro: int) -> None:
        with self._lock:
            tabla, clave = self._tabla(proceso)
            if tabla is None:
                self.listas = [l for l in self.listas if l[clave] != int(id_registro)]
            else:
                tabla.pop(int(id_registro), None)


def _copia(x):
    import copy
    return copy.deepcopy(x)
