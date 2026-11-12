"""
Modelos de la herramienta: las entidades de Tango con nombres claros.

Tango devuelve campos como COD_STA11 o DESCRIPCIO. Aca se traducen una sola
vez a nombres legibles; el resto del programa usa solo estos modelos y no
conoce los nombres internos de Tango.

Los nombres de campo de Tango salen de respuestas reales de la API de Sianco
(Tango Gestion 25.1, 12/11/2026).
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
