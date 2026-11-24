# API de Tango Gestión (Delta): referencia

Todo lo que sabemos de la API de Tango Gestión, en un solo lugar. Junta tres fuentes y en cada punto dice de cuál sale:

- **[Oficial]**: material publicado por Axoft. El repositorio de ejemplo [TangoSoftware/TangoDeltaApi](https://github.com/TangoSoftware/TangoDeltaApi) (C#) y el PDF *API Pedidos v1.11*, cuyo texto está en [`referencia/axoft-api-pedidos-v1.11.txt`](referencia/axoft-api-pedidos-v1.11.txt).
- **[Probado]**: lo que la Herramienta comprobó contra Tango Gestión 25.1 de la oficina (noviembre 2026). Está en `herramienta_tango/tango/`.
- **[Ayuda Axoft]**: la ayuda en línea (`ayudas.axoft.com/…/api_oper/`). Dice que cada proceso trae su API "autodocumentada" adentro del propio Tango. Desde este entorno no se pudo abrir esa página, así que lo que dice no está copiado acá.

> Cuando algo de acá deje de coincidir con Tango, gana Tango. Corregir este archivo y `procesos.py`.

---

## 1. Conexión

| Dato | Valor |
|---|---|
| URL base | La del Tango web de la oficina (la que se ve en el navegador). El ejemplo oficial usa `http://localhost:17000`. Tango Connect (nube): `https://{llave}.connect.axoft.com/Api/…`, con la llave escrita `000000-000` en lugar de `000000/000` |
| Encabezado `ApiAuthorization` | Token de desarrollador. En el Tango web: menú de usuario > **Desarrollador** > **Generar** > **Aceptar** |
| Encabezado `Company` | ID interno de la empresa: el número que va después de `/company/` en la URL del Tango web (`…/company/117/menu/…` → `117`). También es la columna IDEmpresa de la tabla Empresa en la base de diccionario |
| `Accept` | `application/json` |
| `Content-Type` | `application/json` (en Create y Update) |

[Oficial] `BaseServices.cs` arma la URL así: `UriBuilder(TangoUrl) { Path = "api/{acción}", Query = "process={ProcessId}{resto}" }` y manda los tres encabezados en cada pedido.
[Probado] Un token que no se aceptó en Tango, o uno vencido, responde **HTTP 401**.

## 2. Endpoints

Cada entidad o consulta se identifica con un **número de proceso** (`process`), no con una ruta propia.

| Acción | Método y ruta | Parámetros | Respuesta útil | Fuente |
|---|---|---|---|---|
| Listar | `GET api/Get` | `process`, `pageSize`, `pageIndex` (desde 0), `view` (vacío = vista por defecto) | `resultData.list`, `resultData.totalPages` | Oficial + Probado |
| Uno por ID | `GET api/GetById` | `process`, `id`, `view` | `value` (o `resultData`) | Oficial + Probado |
| Filtrar | `GET api/GetByFilter` | `process`, `view`, `filtroSql=WHERE <condición>` (URL-encoded) | `list` | Oficial (no probado) |
| Crear | `POST api/Create` | `process`. Cuerpo: el registro, como lo devuelve GetById, sin ID | `savedId` | Oficial + Probado |
| Modificar | `PUT api/Update` | `process`. Cuerpo: el registro **completo**, con su ID | `succeeded` | Oficial + Probado |
| Borrar | `DELETE api/Delete` | `process`, `id` | `succeeded` | Oficial + Probado |
| Consulta Live | `GET api/GetApiLiveQueryData` | `process`, `fromDate`/`toDate` (`dd/mm/aaaa`), `pageSize`, `pageIndex` | `resultData.list`, `resultData.totalPages` | Probado |
| PDF de un comprobante | `GET Api/GetPdf` | `process` (el del tablero/ficha Live), `id` | `fileResult.fileContents` (base64), `fileResult.fileDownloadName` | Probado |
| Registrar comprobante de venta | `POST FacturadorVenta/registrar` (Connect: `…/Api/FacturadorVenta/registrar`) | sin `process` | `{"Message", "Comprobantes": [...], "Succeeded"}` | Oficial (no probado) |

### Filtros (GetByFilter)

[Oficial] El ejemplo pasa condiciones SQL sobre la tabla o la vista del proceso:

```
GVA01.COND_VTA = 1
GVA10.NOMBRE_LIS = 'Venta Mayorista'
AXV_CLIENTE.COD_GVA14 = '010001'
GVA24.COD_TRANSP = '01'
GVA81.COD_CLASIF = '1'
MONEDA.COD_MONEDA = 'PES'
STA22.COD_STA22 = 1
AXV_ARTICULO.COD_STA11 = '0100100134'
```

En los procesos grandes (Clientes, Artículos, Proveedores, Pedidos) el filtro va contra la vista `AXV_<PROCESO>` (`AXV_CLIENTE`, `AXV_ARTICULO`, `AXV_PEDIDO`) y no contra la tabla (`GVA14`, `STA11`, `GVA21`). La Herramienta todavía no usa GetByFilter: trae todo con `api/Get` y lo guarda en caché.

### Forma de las respuestas

```jsonc
// api/Get y api/GetApiLiveQueryData
{ "succeeded": true, "resultData": { "list": [ {...}, ... ], "totalPages": 3 } }

// api/GetById
{ "succeeded": true, "value": { ... } }                 // si no existe: "value": null

// api/Create, api/Update, api/Delete (TransactionResultModel del ejemplo oficial)
{ "succeeded": true, "savedId": 123, "message": "...",
  "exceptionInfo": { "title": "...", "messages": [...], "detailMessages": [...] } }

// Api/GetPdf
{ "fileResult": { "fileContents": "<base64>", "fileDownloadName": "...pdf" } }
```

### Errores [Probado]

- `succeeded: false` puede venir con HTTP 200: hay que revisarlo siempre.
- `message` trae un texto genérico ("Se detectó una situación inesperada"). El motivo real está en `exceptionInfo.messages` y `exceptionInfo.detailMessages`, que pueden ser textos sueltos u objetos con `message`/`text` (ver `_motivo` en `cliente.py`).
- Un ID que no existe en GetById responde `"value": null` o `succeeded: false` con "Registro inexistente".
- 401: token rechazado.

## 3. Números de proceso

| Proceso | Qué es | Tabla / vista | Endpoint | Fuente |
|---|---|---|---|---|
| 87 | Artículos (también responde 418) | STA11 / AXV_ARTICULO | Get | Oficial + Probado |
| 326 | Clasificación de comprobantes | GVA81 | Get | Oficial |
| 952 | Vendedores | GVA23 | Get | Oficial |
| 960 | Transportes | GVA24 | Get | Oficial |
| 984 | Listas de precios de venta | GVA10 | Get, ABM | Oficial + Probado (alta y baja) |
| 1575 | Cuentas contables | | Get | Oficial |
| 1622 | Tipos de asientos | | Get | Oficial |
| 1656 | Tipos de auxiliares contables | | Get | Oficial |
| 1660 | Monedas | MONEDA | Get | Oficial |
| 1664 | Asientos analíticos (contabilidad) | | Get, Create | Oficial |
| 2117 | Clientes (también responde 2567) | GVA14 / AXV_CLIENTE | Get, GetById, ABM | Oficial + Probado (lectura) |
| 2497 | Condiciones de venta | GVA01 | Get | Oficial |
| 2941 | Depósitos | STA22 | Get | Oficial + Probado |
| 19845 | Pedidos de venta (encabezados) | GVA21 / AXV_PEDIDO | Get, GetById, Create | Oficial + Probado (lectura) |
| 20091 | Precios de venta por artículo y lista (Actualización individual) | GVA17, con GVA13 adentro | Get, GetById, ABM | Probado |
| 20412 | Registro de comprobantes de venta | | `FacturadorVenta/registrar` | Oficial |

Consultas Live (`api/GetApiLiveQueryData`). El número se ve en la URL del Tango web: `/company/<empresa>/live/<proceso>`.

| Proceso | Consulta | Fuente |
|---|---|---|
| 12481 | Ventas > Consultas > Cotizaciones > Detalle (renglones) | Probado |
| 12742 | Ventas > Consultas > Precios > Precios vigentes a una fecha. Lee un historial: **no** refleja lo que se carga por la API | Probado |
| 14062 | Ficha Live de cotizaciones. Con `Api/GetPdf` devuelve el PDF del formulario 128 (`id` = ID_GVA08) | Probado |
| 17668 | Saldos por artículo y depósito (también los que no llevan partidas) | Probado |
| 17686 | Saldos por partida | Probado |
| 17839 | Detalle de comprobantes de venta (renglones, por fecha) | Probado |
| 17948 | Cotizaciones, una por fila | Probado |
| 17965 | Comprobantes de venta, uno por fila (remitos: `TIPO_COMPROBANTE = REM`) | Probado |

Para encontrar un proceso nuevo: abrir la pantalla en el Tango web y mirar el número en la URL. Después probarlo con `api/Get` (maestros) o `api/GetApiLiveQueryData` (consultas Live). [Ayuda Axoft] Según la ayuda, adentro de cada proceso de Tango está su propia documentación de API.

## 4. Reglas generales de los JSON [Oficial: PDF API Pedidos]

- Los `bool` aceptan null y por defecto valen `false`. `null`, `true` y `false` van en minúscula.
- En los `datetime` solo cuenta la fecha, salvo que se diga otra cosa.
- `ID_XXXX` es el ID interno en la tabla `XXXX` (`ID_MONEDA` → tabla MONEDA, `ID_GVA14` → clientes).
- Negativos sin espacio: `-5000`. Decimal con punto.
- Los decimales se redondean a lo configurado en Administrador > Configuración de decimales.
- **Modificar = mandar todo**: Update reemplaza el registro. Un renglón que no se manda queda borrado.

## 5. Escrituras probadas en la oficina [Probado, 17/11/2026]

Hoy la Herramienta solo escribe en el editor de listas de precios (`precios.py`):

- Lista: proceso 984 (GVA10). Create, Update y Delete. No se puede borrar una lista que tenga asignada un cliente.
- Precio de un artículo en una lista: proceso 20091 (GVA17), con el **precio de lista**.
- Precio especial por cliente: GVA13. Viaja adentro del registro de GVA17 (campo `GVA13`, una lista) y se graba con el mismo Update. Las listas de cliente tienen el precio de lista en 0 y el precio real como precio especial.
- Después de cada escritura se vuelve a leer el registro con GetById para confirmar.

## 6. API de Pedidos (alta, modificación, cierre, anulación) [Oficial]

Proceso **19845**. Resumen del PDF v1.11. El detalle campo por campo está en [`referencia/axoft-api-pedidos-v1.11.txt`](referencia/axoft-api-pedidos-v1.11.txt).

- Desde Delta 4 se pueden cargar pedidos de clientes ocasionales. Desde Delta 5 se pueden editar.
- No se pueden cargar pedidos en referencia a cotizaciones.
- Los totales los calcula la API. Los pedidos quedan con origen externo (`GVA21.ORIGEN = 'E'`).
- El `ESTADO` no se edita. No se pueden editar pedidos que ya tienen facturas o remitos.

Encabezado (los obligatorios en **negrita**):
**`ID_GVA43_TALON_PED`** (talonario con COMPROB = PED), `NRO_PEDIDO` (14 dígitos; si no va, se asigna solo), `ESTADO` (1 Ingresado, 2 Aprobado; depende de Parámetros de Ventas > Aprueba pedidos), `FECHA_PEDIDO`, `ID_GVA14` (obligatorio si es cliente habitual), **`ES_CLIENTE_HABITUAL`**, **`ID_GVA01`** (condición de venta), **`ID_GVA23`** (vendedor), **`ID_STA22`** (depósito), **`ID_GVA24`** (transporte), **`ID_MONEDA`**, `COTIZACION`, **`ID_GVA10`** (lista de precios), `ID_DIRECCION_ENTREGA`, `FECHA_ENTREGA`, `ID_ASIENTO_MODELO_GV`, `ID_GVA81`, `ID_GVA43_TALONARIO_FACTURA`, `NRO_ORDEN_COMPRA`, `FECHA_ORDEN_COMPRA`, `ID_SUCURSAL_DESTINO`, `COMPROMETE_STOCK` (por defecto true), `LEYENDA_1`…`LEYENDA_5`, descuentos y recargos generales (porcentaje **o** importe), datos de la RG 3749.

Secciones: `RENGLON_DTO` (renglones: `ID_STA11`, `MODULO_UNIDAD_MEDIDA` como `"GV"`, `CANTIDAD_PEDIDA`, `PRECIO`, bonificación, etc.), `PLAN_DE_ENTREGA_DTO`, `DESCRIPCION_ADICIONAL_DTO`, `CLIENTE_OCASIONAL_DTO`, `CLIENTE_OCASIONAL_PERCEPCIONES_DEFINIBLES_DTO`, `NOTA_PEDIDO_DTO`.

**Cerrar** (`CERRAR`): `ID_GVA21` (obligatorio), `CODIGOMOTIVO` (tabla GVA121), `PROCESO` (se recomienda `"API"`).
**Anular** (`ANULAR`): igual que cerrar, más los booleanos `RECONSTRUIRCOTIZACIONES`, `RECONSTRUIRNEXOTIENDAS`, `ANULARPEDIDOEXPORTADOCENTRAL`, `ANULARPEDIDONEXOTIENDASDEOTRASUCURSAL`, `ANULARPEDIDORELACIONADOCONFACTURAREMITO`, `ANULARPEDIDORELACIONADOCONCOTIZACION` y `VALIDACOMPROBANTESRELACIONADOSDESDETIENDAS`. Todos valen false por defecto. Cerrar y anular se agregaron en la v1.11 (27/10/2026). El PDF no dice a qué ruta se mandan; hay que probarlo.

## 7. Lo que la API no trae [Probado]

- Con qué lista de precios se hizo cada cotización o factura (probado el 20/11/2026). Se lee de la base SQL: `GVA08.ID_GVA10` y `GVA12.NRO_DE_LIS` (`base_tango.py`, solo lectura).
- Movimientos de stock por artículo, carpetas de importación y la relación entre remito y pedido: también se leen de la base SQL.

## 8. Otras APIs de Axoft (otros productos, para no confundir)

- **Tango eCommerce** ([APIeCommerce](https://github.com/TangoSoftware/APIeCommerce)): `https://{llave}.connect.axoft.com/api/eCommerce/...`. Usa los mismos encabezados `ApiAuthorization` y `Company`, pero otras rutas: `Product`, `Stock`, `Price`, `Customer`, `Order`, etc. Pagina con `pageNumber` (desde 1) y `pageSize` (hasta 5000), y responde con `Paging.MoreData`. Pide Delta 6 o superior y la licencia de eCommerce.
- **Tango Tiendas** ([ApiTiendas](https://github.com/TangoSoftware/ApiTiendas)): `https://tiendas.axoft.com/api/Aperture/...`, con encabezado `accesstoken`.
- **Tango Clientes** ([ApiClientes](https://github.com/TangoSoftware/ApiClientes)): comprobantes en JSON.

## Pendiente de completar

- Copiar la ayuda oficial de `ayudas.axoft.com` (versiones 24 y 25: "API" en Apertura de operaciones). Desde este entorno no se pudo abrir.
- Probar `GetByFilter` y la ruta de cerrar y anular pedidos contra el Tango de la oficina.
