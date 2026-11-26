"""
Numeros de proceso de Tango usados por la herramienta.

En la API de Tango cada entidad o consulta se identifica con un numero de
proceso interno. Estos son los que se probaron contra Tango Gestion 25.1
en noviembre de 2026.

- Los de "Get" salen del ejemplo oficial de Axoft (TangoDeltaApi) y
  funcionaron tal cual.
- Los de consultas Live se ven en la URL del Tango web:
  /company/<empresa>/live/<proceso>.

Si una version futura de Tango cambia un numero, se corrige solo aca.
"""

# Maestros (endpoint api/Get)
ARTICULOS = 87              # tambien responde 418
DEPOSITOS = 2941
CLIENTES = 2117             # tambien responde 2567
PEDIDOS = 19845             # encabezados de pedidos de venta
LISTAS_PRECIOS = 984

# Consultas Live (endpoint api/GetApiLiveQueryData)
LIVE_SALDOS_POR_PARTIDA = 17686
LIVE_SALDOS_POR_ARTICULO = 17668     # por articulo y deposito, tambien los que no llevan partidas
LIVE_VENTAS_DETALLE = 17839  # renglones de comprobantes de venta, por fecha
LIVE_COTIZACIONES = 17948      # Ventas > Consultas > Cotizaciones > Consulta (una por fila)
LIVE_COTIZACIONES_DETALLE = 12481  # Ventas > Consultas > Cotizaciones > Detalle (renglones)
# PDF de facturas y pedidos: Api/GetPdf con alguno de estos procesos (se prueban en orden y se
# recuerda el que anduvo). Sin confirmar en el Tango de Sianco: el numero correcto es el que
# muestra Apertura -> API (GetPdf) en la pantalla del comprobante en el Tango web.
PDF_FACTURA = (14077,)                        # Ficha Live de facturas, creditos y debitos (id = ID_GVA12).
                                              # 17965/17839/11663 responden "GetPdfContentById no implementado"
PDF_REMITO = (14093,)                         # Ficha Live de remitos (id = ID_STA14)
PDF_PEDIDO = (19845, 2007, 12481)             # id = ID_GVA21
TABLERO_FICHA_COTIZACION = 14062   # Ficha Live de cotizaciones: Api/GetPdf con este proceso
                                   # devuelve el PDF del formulario 128 (id = ID_GVA08)
LIVE_COMPROBANTES_VENTA = 17965   # comprobantes de venta, uno por fila (remitos: TIPO_COMPROBANTE = REM)
LIVE_PRECIOS_VIGENTES = 12742  # Ventas > Consultas > Precios > Precios vigentes a una fecha

# Pantalla de carga de precios (Ventas > Archivos > Actualizaciones > Precios de venta >
# Actualizacion individual). Tabla GVA17. Para las listas por cliente muestra 0 en
# lugar del precio que aparece en la consulta 12742; no se usa hasta aclarar por que.
PRECIOS_ABM = 20091
