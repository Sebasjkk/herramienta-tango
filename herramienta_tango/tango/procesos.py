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
LIVE_VENTAS_DETALLE = 17839  # renglones de comprobantes de venta, por fecha
LIVE_PRECIOS_VIGENTES = 12742  # Ventas > Consultas > Precios > Precios vigentes a una fecha

# Pantalla de carga de precios (Ventas > Archivos > Actualizaciones > Precios de venta >
# Actualizacion individual). Tabla GVA17. Para las listas por cliente muestra 0 en
# lugar del precio que aparece en la consulta 12742; no se usa hasta aclarar por que.
PRECIOS_ABM = 20091
