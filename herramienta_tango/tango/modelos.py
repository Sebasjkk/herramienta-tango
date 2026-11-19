"""
Modelos de la herramienta: las entidades de Tango con nombres claros.

Tango devuelve campos como COD_STA11 o DESCRIPCIO. Aca se traducen una sola
vez a nombres legibles; el resto del programa usa solo estos modelos y no
conoce los nombres internos de Tango.

Los nombres de campo de Tango salen de respuestas reales de la API de
Tango Gestion 25.1 (noviembre de 2026).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ----------------------------------------------------------------- utilidades
def _txt(valor: Any) -> str:
    return "" if valor is None else str(valor).strip()


def _num(valor: Any) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _fecha(valor: Any) -> str | None:
    """Fecha ISO (AAAA-MM-DD) o None."""
    t = _txt(valor)
    return t[:10] if t else None


def _bool(valor: Any) -> bool:
    if isinstance(valor, bool):
        return valor
    return _txt(valor).upper() in ("S", "SI", "TRUE", "1")


# --------------------------------------------------------------------- stock
@dataclass(frozen=True)
class SaldoPartida:
    id_partida: int | None
    codigo_articulo: str
    descripcion: str
    deposito: str
    partida: str
    despacho: str
    vencimiento: str | None
    unidad: str
    saldo: float

    @classmethod
    def desde_tango(cls, x: dict) -> "SaldoPartida":
        return cls(
            id_partida=x.get("ID_STA08"),
            codigo_articulo=_txt(x.get("COD_ARTICULO")),
            descripcion=_txt(x.get("DESCRIPCION")),
            deposito=_txt(x.get("DESCRIPCION_DEPOSITO")),
            partida=_txt(x.get("PARTIDA")),
            despacho=_txt(x.get("NUMERO_DE_DESPACHO")),
            vencimiento=_fecha(x.get("FECHA_DE_VENCIMIENTO")),
            unidad=_txt(x.get("UM_CONTROL_STOCK")),
            saldo=round(_num(x.get("SALDO_CONTROL_STOCK")), 4),
        )


@dataclass(frozen=True)
class SaldoArticulo:
    """Saldo de un articulo en un deposito (consulta Live 17668), lleve o no partidas."""
    id_articulo: int | None
    codigo_articulo: str
    descripcion: str
    deposito: str
    unidad: str
    saldo: float
    comprometido: float
    a_recibir: float

    @classmethod
    def desde_tango(cls, x: dict) -> "SaldoArticulo":
        return cls(
            id_articulo=x.get("ID_STA11"),
            codigo_articulo=_txt(x.get("COD_ARTICULO")),
            descripcion=_txt(x.get("DESCRIPCION")),
            deposito=_txt(x.get("DESCRIPCION_DEPOSITO")),
            unidad=_txt(x.get("UM_CONTROL_STOCK")),
            saldo=round(_num(x.get("SALDO_CONTROL_STOCK")), 4),
            comprometido=round(_num(x.get("CANTIDAD_COMPROMETIDA_CONTROL_STOCK")), 4),
            a_recibir=round(_num(x.get("CANTIDAD_A_RECIBIR_CONTROL_STOCK")), 4),
        )


@dataclass(frozen=True)
class Articulo:
    id: int | None
    codigo: str
    descripcion: str
    descripcion_adicional: str
    sinonimo: str
    codigo_barras: str
    usa_partidas: bool
    lleva_stock: bool
    perfil: str
    unidad: str
    ncm: str
    stock_minimo: float
    stock_maximo: float
    punto_pedido: float

    @classmethod
    def desde_tango(cls, x: dict) -> "Articulo":
        return cls(
            id=x.get("ID_STA11"),
            codigo=_txt(x.get("COD_STA11")),
            descripcion=_txt(x.get("DESCRIPCIO")),
            descripcion_adicional=_txt(x.get("DESC_ADIC")),
            sinonimo=_txt(x.get("SINONIMO")),
            codigo_barras=_txt(x.get("COD_BARRA")),
            usa_partidas=_bool(x.get("USA_PARTID")),
            lleva_stock=_bool(x.get("STOCK")),
            perfil=_txt(x.get("PERFIL")),
            unidad=_txt(x.get("MEDIDA_STOCK_SIGLA") or x.get("MEDIDA_STOCK_CODIGO")),
            ncm=_txt(x.get("COD_NCM")),
            stock_minimo=_num(x.get("STOCK_MINI")),
            stock_maximo=_num(x.get("STOCK_MAXI")),
            punto_pedido=_num(x.get("PTO_PEDIDO")),
        )


@dataclass(frozen=True)
class Deposito:
    id: int | None
    codigo: str
    nombre: str
    direccion: str
    inhabilitado: bool

    @classmethod
    def desde_tango(cls, x: dict) -> "Deposito":
        return cls(
            id=x.get("ID_STA22"),
            codigo=_txt(x.get("COD_STA22")),
            nombre=_txt(x.get("NOMBRE_SUC")),
            direccion=_txt(x.get("DIR_SUCURS")),
            inhabilitado=_bool(x.get("INHABILITA")),
        )


# --------------------------------------------------------------------- ventas
@dataclass(frozen=True)
class Cliente:
    id: int | None
    codigo: str
    razon_social: str
    cuit: str
    habilitado: bool
    lista_precios: str

    @classmethod
    def desde_tango(cls, x: dict) -> "Cliente":
        return cls(
            id=x.get("ID_GVA14"),
            codigo=_txt(x.get("COD_GVA14")),
            razon_social=_txt(x.get("RAZON_SOCI")),
            cuit=_txt(x.get("CUIT")),
            habilitado=_bool(x.get("HABILITADO")),
            lista_precios=_txt(x.get("GVA10_NOMBRE_LIS")),
        )


@dataclass(frozen=True)
class Pedido:
    id: int | None
    numero: str
    codigo_cliente: str
    cliente: str
    fecha: str | None
    fecha_entrega: str | None
    estado: int | None
    orden_compra_cliente: str
    fecha_orden_compra: str | None
    deposito: str
    lista_precios: str
    total: float
    leyendas: tuple[str, ...]
    numero_remito: str = ""

    @classmethod
    def desde_tango(cls, x: dict) -> "Pedido":
        leyendas = tuple(_txt(x.get(f"LEYENDA_{i}")) for i in range(1, 6))
        return cls(
            id=x.get("ID_GVA21"),
            numero=_txt(x.get("NRO_PEDIDO")),
            codigo_cliente=_txt(x.get("CODIGO_CLIENTE")),
            cliente=_txt(x.get("RAZON_SOCIAL_CLIENTE")),
            fecha=_fecha(x.get("FECHA_PEDI")),
            fecha_entrega=_fecha(x.get("FECHA_ENTR")),
            estado=x.get("ESTADO"),
            orden_compra_cliente=_txt(x.get("NRO_OC_COMP")),
            fecha_orden_compra=_fecha(x.get("FECHA_O_COMP")),
            deposito=_txt(x.get("NOMBRE_SUC")),
            lista_precios=_txt(x.get("NOMBRE_LIS")),
            total=_num(x.get("TOTAL_PEDI")),
            leyendas=tuple(l for l in leyendas if l),
            numero_remito=_txt(x.get("N_REMITO")),
        )


@dataclass(frozen=True)
class ListaPrecios:
    id: int | None
    numero: int | None
    nombre: str
    habilitada: bool
    incluye_iva: bool
    moneda_corriente: bool

    @classmethod
    def desde_tango(cls, x: dict) -> "ListaPrecios":
        return cls(
            id=x.get("ID_GVA10"),
            numero=x.get("NRO_DE_LIS"),
            nombre=_txt(x.get("NOMBRE_LIS")),
            habilitada=_bool(x.get("HABILITADA")),
            incluye_iva=_bool(x.get("INCLUY_IVA")),
            moneda_corriente=_bool(x.get("MON_CTE")),
        )


@dataclass(frozen=True)
class PrecioEspecial:
    """Precio de un articulo en una lista para un cliente puntual (GVA13).
    Las listas de cliente (SCIPIO, TECSPRAY...) tienen el precio de lista en 0
    y el precio real aca."""
    id: int | None
    id_cliente: int | None
    codigo_cliente: str
    precio: float

    @classmethod
    def desde_tango(cls, x: dict) -> "PrecioEspecial":
        return cls(id=x.get("ID_GVA13"), id_cliente=x.get("ID_GVA14"),
                   codigo_cliente=_txt(x.get("COD_CLIENT")), precio=_num(x.get("PRECIO")))


@dataclass(frozen=True)
class RenglonPrecio:
    """Un articulo dentro de una lista de precios (GVA17, proceso 20091)."""
    id: int
    id_lista: int | None
    numero_lista: int | None
    id_articulo: int | None
    codigo_articulo: str
    descripcion: str
    precio: float                      # precio de lista
    modificado: str | None
    especiales: tuple[PrecioEspecial, ...] | None   # None: no se leyeron (lista muy grande)

    @classmethod
    def desde_tango(cls, x: dict, detalle: dict | None = None) -> "RenglonPrecio":
        """x: renglon de api/Get. detalle: el mismo renglon por GetById (trae los especiales)."""
        especiales = None
        if detalle is not None:
            especiales = tuple(PrecioEspecial.desde_tango(c) for c in (detalle.get("GVA13") or []))
        return cls(
            id=int(x.get("ID_GVA17")),
            id_lista=x.get("ID_GVA10"),
            numero_lista=x.get("NRO_DE_LIS"),
            id_articulo=x.get("ID_STA11"),
            codigo_articulo=_txt(x.get("COD_STA11") or x.get("COD_ARTICU")),
            descripcion=_txt(x.get("DESCRIPCIO")),
            precio=_num((detalle or x).get("PRECIO")),
            modificado=_fecha(x.get("FECHA_MODI")),
            especiales=especiales,
        )


@dataclass(frozen=True)
class PrecioVigente:
    """Un precio de un articulo en una lista, tal como lo muestra la consulta
    Precios vigentes a una fecha. Si el precio es propio de un cliente, viene el cliente."""
    codigo_articulo: str
    descripcion: str
    numero_lista: int | None
    lista: str
    precio: float
    moneda: str              # "$" (moneda corriente) o "US$" (extranjera)
    codigo_cliente: str
    cliente: str
    modificado: str | None   # AAAA-MM-DD

    @classmethod
    def desde_tango(cls, x: dict) -> "PrecioVigente":
        nro = x.get("NRO_LISTA_DE_PRECIOS")
        return cls(
            codigo_articulo=_txt(x.get("COD_ARTICULO")),
            descripcion=_txt(x.get("DESCRIPCION")),
            numero_lista=nro,
            lista=_txt(x.get("DESC_LISTA_DE_PRECIOS")) or (f"Lista {nro}" if nro is not None else ""),
            precio=_num(x.get("PRECIO")),
            moneda="$" if _bool(x.get("MONEDA")) else "US$",
            codigo_cliente=_txt(x.get("COD_CLIENTE")),
            cliente=_txt(x.get("RAZON_SOCIAL")),
            modificado=_fecha(x.get("FECHA_MODIFICACION")),
        )


ESTADOS_COTIZACION = {2: "Autorizada", 4: "Procesada", 5: "Anulada"}   # vistos en Tango el 17/11/2026


def _primero(x: dict, *claves):
    """El primer campo que exista: las consultas Live no siempre usan el mismo nombre."""
    for c in claves:
        if c in x and x[c] is not None:
            return x[c]
    return None


@dataclass(frozen=True)
class Cotizacion:
    id: int | None
    talonario: int | None
    numero: str              # tal cual Tango: "0000100003215"
    numero_corto: str        # como lo imprime el formulario: "BA3215"
    fecha: str | None
    vigencia: str | None
    codigo_cliente: str
    cliente: str
    vendedor: str
    estado: int | None
    estado_texto: str
    moneda: str
    perdida: bool

    @classmethod
    def desde_tango(cls, x: dict) -> "Cotizacion":
        numero = _txt(x.get("NRO_COTIZACION"))
        estado = x.get("ESTADO")
        return cls(
            id=x.get("ID_GVA08"),
            talonario=x.get("TALONARIO"),
            numero=numero,
            numero_corto="BA" + str(int(numero[-8:])) if numero[-8:].isdigit() else numero,
            fecha=_fecha(x.get("FECHA")),
            vigencia=_fecha(x.get("FECHA_DE_VIGENCIA")),
            codigo_cliente=_txt(x.get("COD_CLIENTE")),
            cliente=_txt(x.get("RAZON_SOCIAL")),
            vendedor=_txt(x.get("VENDEDOR")),
            estado=estado,
            estado_texto=ESTADOS_COTIZACION.get(estado, f"Estado {estado}"),
            moneda="$" if _bool(x.get("MONEDA")) else "US$",
            perdida=_bool(x.get("PERDIDA")),
        )


@dataclass(frozen=True)
class RenglonCotizacion:
    numero: str
    codigo_articulo: str
    descripcion: str
    cantidad: float
    precio: float
    descuento: float
    pendiente: float | None

    @classmethod
    def desde_tango(cls, x: dict) -> "RenglonCotizacion":
        pendiente = _primero(x, "SALDO_PENDIENTE", "CANTIDAD_PENDIENTE", "PENDIENTE", "CANT_PENDIENTE")
        return cls(
            numero=_txt(_primero(x, "NRO_COTIZACION", "NUMERO_COTIZACION", "N_COTIZACION")),
            codigo_articulo=_txt(_primero(x, "COD_ARTICULO", "COD_STA11", "COD_ARTICU")),
            descripcion=_txt(_primero(x, "DESCRIPCION", "DESCRIPCION_ARTICULO", "DESCRIPCIO")),
            cantidad=_num(_primero(x, "CANTIDAD", "CANT_COTIZADA", "CANTIDAD_COTIZADA")),
            precio=_num(_primero(x, "PRECIO", "PRECIO_UNITARIO")),
            descuento=_num(_primero(x, "PORC_DESCUENTO", "DESCUENTO", "PORCENTAJE_DESCUENTO", "BONIFICACION")),
            pendiente=None if pendiente is None else _num(pendiente),
        )


def solo_digitos(texto: str) -> str:
    return "".join(c for c in (texto or "") if c.isdigit())


@dataclass(frozen=True)
class Remito:
    id: int | None              # ID_STA14 (movimiento de stock)
    numero: str                 # tal cual Tango: "R0000800000110"
    numero_corto: str           # "R 00008-00000110"
    fecha: str | None
    id_cliente: int | None
    codigo_cliente: str
    cliente: str
    estado: str
    orden_compra: str = ""      # de un pedido que referencia este remito, si hay
    pedido: str = ""

    @classmethod
    def desde_tango(cls, x: dict) -> "Remito":
        numero = _txt(x.get("NRO_COMPROBANTE"))
        d = solo_digitos(numero)
        letra = numero[:1] if numero[:1].isalpha() else ""
        corto = f"{letra} {d[:-8]}-{d[-8:]}".strip() if len(d) > 8 else numero
        return cls(id=x.get("ID_STA14"), numero=numero, numero_corto=corto, fecha=_fecha(x.get("FECHA")),
                   id_cliente=x.get("ID_GVA14"), codigo_cliente=_txt(x.get("COD_CLIENTE")),
                   cliente=_txt(x.get("RAZON_SOCIAL")), estado=_txt(x.get("ESTADO")))


PROVINCIAS = {"01": "Capital Federal", "02": "Buenos Aires"}   # codigos de Tango vistos; el resto se completa a mano


@dataclass(frozen=True)
class DireccionEntrega:
    codigo: str
    direccion: str
    localidad: str
    codigo_postal: str
    provincia: str
    telefono: str
    habitual: bool

    @classmethod
    def desde_tango(cls, x: dict) -> "DireccionEntrega":
        return cls(codigo=_txt(x.get("COD_DIRECCION_ENTREGA")), direccion=_txt(x.get("DIRECCION")),
                   localidad=_txt(x.get("LOCALIDAD")), codigo_postal=_txt(x.get("CODIGO_POSTAL")),
                   provincia=PROVINCIAS.get(_txt(x.get("COD_PROVINCIA")), ""), telefono=_txt(x.get("TELEFONO1")),
                   habitual=_txt(x.get("HABITUAL")).upper() == "S")


@dataclass(frozen=True)
class DatosEnvio:
    """Lo que hace falta de un cliente para la etiqueta del bulto."""
    codigo: str
    razon_social: str
    direcciones: tuple[DireccionEntrega, ...]
    contacto: str

    @classmethod
    def desde_tango(cls, x: dict) -> "DatosEnvio":
        dirs = [DireccionEntrega.desde_tango(d) for d in (x.get("DIRECCION_ENTREGA") or [])
                if _txt(d.get("HABILITADO") or "S").upper() != "N"]
        if not dirs and _txt(x.get("DOMICILIO")):
            dirs = [DireccionEntrega("DOMICILIO", _txt(x.get("DOMICILIO")), _txt(x.get("LOCALIDAD")),
                                     _txt(x.get("C_POSTAL")), PROVINCIAS.get(_txt(x.get("COD_PROVIN")), ""),
                                     _txt(x.get("TELEFONO_1")), True)]
        dirs.sort(key=lambda d: not d.habitual)
        contactos = x.get("CONTACTOS") or []
        defecto = next((c for c in contactos if _txt(c.get("DEFECTO")).upper() == "S"), contactos[0] if contactos else {})
        return cls(codigo=_txt(x.get("COD_GVA14")), razon_social=_txt(x.get("RAZON_SOCI")),
                   direcciones=tuple(dirs), contacto=_txt(defecto.get("NOMBRE")))


@dataclass(frozen=True)
class RenglonVenta:
    fecha: str | None
    tipo_comprobante: str
    numero_comprobante: str
    cliente: str
    vendedor: str
    codigo_articulo: str
    descripcion: str
    cantidad: float
    total: float

    @classmethod
    def desde_tango(cls, x: dict) -> "RenglonVenta":
        return cls(
            fecha=_fecha(x.get("FECHA_DE_EMISION")),
            tipo_comprobante=_txt(x.get("TIPO_COMPROBANTE")),
            numero_comprobante=_txt(x.get("NRO_COMPROBANTE")),
            cliente=_txt(x.get("RAZON_SOCIAL")),
            vendedor=_txt(x.get("NOMBRE_VENDEDOR")),
            codigo_articulo=_txt(x.get("COD_ARTICULO")),
            descripcion=_txt(x.get("DESCRIPCION")),
            cantidad=_num(x.get("CANTIDAD")),
            total=_num(x.get("TOTAL")),
        )
