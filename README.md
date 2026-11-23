# Herramienta Tango

Capa intermedia entre Tango Gestión y las herramientas internas de la empresa. Habla con la API de Tango, traduce sus datos a nombres claros y los ofrece en la red de la oficina: como páginas para el celular y como una API propia que cualquier otro programa puede usar.

Hoy es **solo lectura**: no carga ni modifica nada en Tango.

## Módulos

| Módulo | Estado | Dónde |
|---|---|---|
| Inicio | Listo | Resumen: cotizaciones por vencer, pedidos pendientes, stock negativo o bajo punto de pedido, mezclas sin subir, últimos cambios de precios |
| Buscar artículo | Listo | Buscar (`/buscar`): catálogo completo con filtros y orden, vistos hace poco; ficha con stock por lote, movimientos (base), precios y cotizaciones |
| Clientes | Listo | Clientes (`/clientes`): lista de precios, precios especiales, pedidos, cotizaciones y direcciones de entrega |
| Stock por partida | Listo | Stock |
| Listas de precios | Ver y modificar | Precios |
| Cotizaciones | Ver, por estado, y reimprimir el PDF de Tango | Cotizaciones |
| Etiquetas de envío | Etiqueta 10 × 15 cm desde un remito (Zebra ZD220) | Etiquetas |

Las páginas para los usuarios comparten `comun.css` y `comun.js` (navegación: barra lateral en la PC, pestañas abajo en el celular con "Más" para los módulos que no entran; esqueletos de carga, errores que dicen si falló la red, Tango o la Herramienta, colores de estado comunes).

Las pantallas muestran al instante lo último que se vio en ese equipo (guardado en el navegador, con su hora) mientras piden lo nuevo a Tango. Lo que se ve se puede exportar a Excel (`POST /api/exportar`, el .xlsx lo arma `xlsx.py` sin librerías). Precios: después de cambiar o quitar un precio queda unos segundos un botón Deshacer. Mezclas: Repetir copia una mezcla anterior y se sugiere la última partida usada de cada polvo. Stock: «Comparar con inventario Excel» sube el Inventario_Metco y muestra las diferencias con Tango (`inventario.py`; los .xls viejos los lee `xls.py`, sin librerías). Pedidos: entregas parciales (etiqueta, barra de avance y filtro), y en la ficha pedido / entregado / falta por artículo con los remitos del pedido.

Cada pantalla se puede abrir directo con un link: `/clientes?ver=<código>`, `/buscar?art=<código>`, `/buscar?q=zinc&f=neg`, `/pedidos?ver=<id>`, `/cotizaciones?ver=<id>`. Los links viejos `/?q=` redirigen a `/buscar`. Un módulo nuevo se agrega en `MODULOS` de `comun.js`. El panel del servidor (`panel.html`) es aparte.

## Cómo está armado

El programa corre con el **Python oficial** embebido (`pythonw.exe`, firmado por la Python Software Foundation) y su código son archivos `.py`. No hay un `.exe` propio: así los antivirus (Avast, Defender) no lo confunden con algo peligroso.

Instalado en la PC queda así:

```
C:\HerramientaTango\
  Abrir Herramienta Tango.cmd    abre el programa (la primera vez crea los accesos directos)
  python\                        Python oficial embebido (no cambia)
  app\                           código del programa (es lo que se actualiza)
  config.ini, token.dat, herramienta_tango.log   datos (no se tocan al actualizar)
```

Código en este repositorio:

```
HerramientaTango.pyw           punto de entrada
herramienta_tango/
  tango/
    cliente.py                 única parte que habla con la API de Tango (solo GET)
    procesos.py                números de proceso de Tango, en un solo lugar
    modelos.py                 entidades con nombres claros (Articulo, SaldoPartida, Pedido...)
    servicio.py                puerta única hacia Tango, con caché
  web/
    servidor.py                API propia + panel + páginas
    estatico/                  panel de la PC, menú y módulos para el celular
  config.py                    config.ini y carpetas
  credenciales.py              token de Tango cifrado (DPAPI)
  actualizador.py              actualización automática desde los Releases
  contexto.py                  estado del programa y acciones del panel
  sistema.py                   Windows: instalación, inicio automático, accesos directos, avisos
recursos/icono.ico             ícono de los accesos directos
scripts/armar_paquete.ps1      arma el paquete para Windows (lo usa el workflow)
tests/                         pruebas (sin Tango real)
```

Para agregar algo nuevo: el dato se pide a `ServicioTango`, nunca directo a la API de Tango. Si Tango no lo trae todavía, se agrega primero el proceso en `procesos.py`, el modelo en `modelos.py` y el método en `servicio.py`. Cada módulo nuevo se suma a la lista `MODULOS` de `web/estatico/comun.js`.

## API propia (red local)

Todas responden `{"ok": true, "actualizado": "...", "datos": [...]}`. Con `?refrescar=1` se saltea la caché.

| Ruta | Qué devuelve |
|---|---|
| `/api/estado` | Versión del programa |
| `/api/stock/partidas` | Saldo por partida (artículo, depósito, lote, despacho, vencimiento, saldo) |
| `/api/articulos` | Artículos (código, descripción, código de barras, NCM, usa partidas, punto de pedido...) |
| `POST /api/inventario/comparar` | Compara el Excel de inventario (Inventario_Metco, .xls o .xlsx) con el stock de Tango: diferencias contra Central, lo que no está en Tango, lo que solo está en Tango, y un Excel con todo. No modifica Tango |
| `/api/pedidos/avance` | Cuánto se entregó de cada pedido pendiente: sin entregar, parcial o entregado, con porcentaje y lo que falta |
| `/api/pedidos/<id>/remitos` | Remitos y devoluciones hechos contra el pedido (base, solo lectura; busca la columna que une remito y pedido en esa versión de Tango) |
| `/api/articulos/<código>/movimientos` | Últimos 60 movimientos de stock del artículo (base SQL, solo lectura; desde otras PCs se le pide al servidor) |
| `/api/articulos/<código>/cotizaciones` | Cotizaciones donde aparece un artículo, con cantidad y precio (las más nuevas primero) |
| `/api/depositos` | Depósitos |
| `/api/clientes` | Clientes (código, razón social, CUIT, lista de precios) |
| `/api/pedidos` | Pedidos de venta (encabezado, con OC del cliente) |
| `/api/listas-precios` | Listas de precios |
| `/api/precios` | Precios vigentes de todas las listas (artículo, lista, precio, moneda, cliente) |
| `/api/ventas?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Renglones de comprobantes de venta (máx. 366 días) |

## Cómo se genera el paquete

Cada vez que se sube un cambio a `main`, GitHub Actions corre las pruebas, arma el paquete en una máquina Windows (bajando el Python embebido oficial y verificando su firma), prueba que arranque, que cree los accesos directos y que se actualice solo, y lo publica en **Releases** con un número de versión nuevo.

- Primera instalación: pestaña **Releases**, archivo `HerramientaTango.zip`.
- Para generar de nuevo sin cambiar código: **Actions** > "Generar paquete" > **Run workflow**.

## Instalarlo en la PC de la oficina

1. Bajá `HerramientaTango.zip` de la última versión. Antes de descomprimirlo: clic derecho > Propiedades > tildá **Desbloquear** > Aceptar (así Windows no avisa por cada archivo).
2. Descomprimilo en `C:\` (queda `C:\HerramientaTango`) y abrí **Abrir Herramienta Tango**. No aparece ninguna ventana negra: se abre el **panel** en el navegador, y se crea el acceso directo **Herramienta Tango** en el escritorio y en el menú Inicio. De ahí en adelante se abre desde ese acceso directo.
3. La primera vez, el panel pide dos datos y los prueba contra Tango antes de guardarlos:
   - **Dirección del servidor de Tango**: la que se ve en el navegador al abrir el Tango web (se puede pegar entera).
   - **Token de Tango**: en el Tango web, menú de usuario > Desarrollador > Generar > **Aceptar**.
   - Dejá marcada la opción **Abrir el programa solo al prender la PC**.
4. Si Windows pregunta si permite el acceso a la red (aparece como "Python"), elegí **Permitir**. Si la red figura como "Pública", marcá también esa opción.
5. En el panel aparece un **código QR**: se escanea con el celular (conectado al Wi-Fi de la oficina) y abre el menú.

Si se vuelve a abrir con el programa ya funcionando, solo abre el panel. El panel (`http://127.0.0.1:8085/panel`) solo funciona desde la misma PC.

## Modo servidor (recomendado en la PC que queda siempre prendida)

Lo ideal es instalarlo en el **servidor de Tango**, que está siempre prendido. En el panel: Ajustes > **Modo servidor** > **Activar**. Windows pide permiso de administrador una sola vez, y después:

- El programa corre como **tarea programada de Windows** con la cuenta SYSTEM: arranca al prender la PC **aunque nadie inicie sesión**.
- Un vigilante lo vuelve a abrir si se cae, y después de cada actualización.
- Se agrega la regla **Herramienta Tango** al firewall, que deja entrar al puerto 8085 solo desde redes privadas (10.x, 172.16-31.x, 192.168.x).
- Se deja de usar "Abrir al prender la PC" (ya no hace falta).

El token se guarda cifrado a nivel equipo (DPAPI de la máquina): lo puede leer cualquier programa de esa PC, pero copiado a otra no sirve. Para volver al modo normal: **Desactivar** en el mismo lugar.

**Cómo entran los demás**

- **Otras PCs:** `http://NOMBRE-DEL-SERVIDOR:8085`. Al pie del menú está **Descargar acceso directo** (un archivo `.url` que se copia al escritorio).
- **Celulares:** el QR del panel. Después, en Chrome: menú ⋮ > **Agregar a la pantalla principal**, y queda un ícono como el de una app. Usa la IP del servidor, así que conviene reservarle una IP fija en el router.

## Actualizaciones automáticas

El programa se actualiza solo. Cada 15 minutos consulta los Releases de este repositorio (o en el momento, con **Buscar actualizaciones** en el panel) y, si hay una versión nueva:

1. Descarga `HerramientaTango-app.zip` (solo el código, unos cientos de KB) y verifica su SHA-256 contra `HerramientaTango-app.zip.sha256`. Si no coincide, no instala nada.
2. Lo descomprime aparte, comprueba que esté completo y cambia la carpeta `app` por la nueva (la anterior queda como `app.old` hasta el próximo arranque). Si algo falla, vuelve todo como estaba.
3. Se reinicia solo. El corte dura unos segundos y el panel y el celular se recargan solos.

`config.ini`, `token.dat` y el Python embebido no se tocan. En `config.ini`, sección `[actualizaciones]`: `automatica = no` hace que solo avise, y `cada_minutos` cambia la frecuencia. La PC necesita salida a internet hacia github.com.

Ojo: cualquiera con permiso de escritura en este repositorio puede publicar una versión que la PC de la oficina va a instalar sola. Conviene tener activada la verificación en dos pasos en las cuentas de GitHub que tienen acceso.

## Si algo falla

| Lo que se ve | Qué hacer |
|---|---|
| El panel dice "Tango rechazó el token" | Generá un token nuevo en Tango (Desarrollador > Generar > Aceptar) y cargalo en Ajustes > Servidor y token. |
| El panel dice "Sin conexión con Tango" | Revisá que el servidor de Tango esté prendido y la dirección en Ajustes > Servidor y token. |
| El celular no abre la página | El celular tiene que estar en el Wi-Fi de la oficina. Revisá el permiso del firewall. Si el panel muestra otras direcciones, probá con esas. |
| Aviso "el puerto 8085 está ocupado" | Otro programa usa ese puerto: cambiá `puerto` en `config.ini`. |
| El antivirus bloquea algo | Agregá `C:\HerramientaTango` como excepción en el antivirus. |
| Algo no funciona y no se ve por qué | Mirá `herramienta_tango.log` en la carpeta del programa. |

## Modificar listas de precios

Cualquier equipo de la red de la oficina puede modificar: no hay claves (quien llega a la red ya llega a Tango,
y la Herramienta no sale a internet). La primera vez que alguien modifica desde un equipo, la página le pregunta
el nombre y el equipo lo recuerda; el registro guarda ese nombre y la IP.

Cómo guarda Tango los precios (verificado el 17/11/2026 con una lista de prueba):

- Lista: tabla GVA10, proceso 984.
- Artículo en una lista: GVA17, proceso 20091, con el **precio de lista**.
- **Precio especial por cliente**: GVA13, que viaja adentro del renglón de GVA17 (campo `GVA13`) y se graba con el mismo `Update`.
  Las listas de cliente (SCIPIO, TECSPRAY...) tienen el precio de lista en 0 y el precio real como precio especial del cliente;
  el editor respeta eso: en esas listas cambia y agrega precios especiales del cliente.
- La consulta «Precios vigentes a una fecha» (12742) lee un historial y no refleja lo que se carga por la API: no se usa para editar.

Cada cambio se verifica volviendo a leer el registro y queda en `cambios_precios.jsonl` (quién, cuándo, antes y después;
al eliminar una lista, también todo su contenido). No se puede eliminar una lista que un cliente tiene asignada en Tango.
Una lista nueva hay que asignársela al cliente en su ficha en Tango.

## Límites actuales

- Stock por partida muestra solo artículos que llevan partidas.
- Lo único que escribe en Tango es el editor de listas de precios (ver abajo).
- Funciona solo dentro de la red de la oficina, a propósito: el token de Tango viaja sin cifrar y la API propia no pide clave.

## Desarrollo

```
python -m unittest discover -s tests      # pruebas
python HerramientaTango.pyw               # correrlo desde el código (abre el panel)
```

Solo usa la librería estándar de Python 3.10 o superior.
