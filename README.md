# Herramienta Tango

Capa intermedia entre Tango Gestión y las herramientas internas de la empresa. Habla con la API de Tango, traduce sus datos a nombres claros y los ofrece en la red de la oficina: como páginas para el celular y como una API propia que cualquier otro programa puede usar.

Hoy es **solo lectura**: no carga ni modifica nada en Tango.

## Módulos

| Módulo | Estado | Dónde |
|---|---|---|
| Stock por partida | Listo | Menú → Stock por partida |
| Listas de precios | Solo lectura | Menú → Listas de precios |

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

Para agregar algo nuevo: el dato se pide a `ServicioTango`, nunca directo a la API de Tango. Si Tango no lo trae todavía, se agrega primero el proceso en `procesos.py`, el modelo en `modelos.py` y el método en `servicio.py`. Cada módulo nuevo se suma a la lista `MODULOS` del menú (`web/estatico/index.html`).

## API propia (red local)

Todas responden `{"ok": true, "actualizado": "...", "datos": [...]}`. Con `?refrescar=1` se saltea la caché.

| Ruta | Qué devuelve |
|---|---|
| `/api/estado` | Versión del programa |
| `/api/stock/partidas` | Saldo por partida (artículo, depósito, lote, despacho, vencimiento, saldo) |
| `/api/articulos` | Artículos (código, descripción, código de barras, NCM, usa partidas, punto de pedido...) |
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

## Límites actuales

- Stock por partida muestra solo artículos que llevan partidas.
- No hay escritura en Tango.
- Los precios se leen de la consulta «Precios vigentes a una fecha» (12742). La pantalla de carga de precios (20091) muestra 0 en las listas por cliente; hasta saber cuál de las dos usa Tango al facturar, no se cambian precios desde acá.
- Funciona solo dentro de la red de la oficina, a propósito: el token de Tango viaja sin cifrar y la API propia no pide clave.

## Desarrollo

```
python -m unittest discover -s tests      # pruebas
python HerramientaTango.pyw               # correrlo desde el código (abre el panel)
```

Solo usa la librería estándar de Python 3.10 o superior.
