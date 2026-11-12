# Herramienta Tango

Capa intermedia entre Tango Gestión y las herramientas internas de la empresa. Habla con la API de Tango, traduce sus datos a nombres claros y los ofrece en la red de la oficina: como páginas para el celular y como una API propia que cualquier otro programa puede usar.

Hoy es **solo lectura**: no carga ni modifica nada en Tango.

## Módulos

| Módulo | Estado | Dónde |
|---|---|---|
| Stock por partida | Listo | Página principal |

## Cómo está armado

```
HerramientaTango.py            punto de entrada (el que se convierte en .exe)
herramienta_tango/
  tango/
    cliente.py                 única parte que habla con la API de Tango (solo GET)
    procesos.py                números de proceso de Tango, en un solo lugar
    modelos.py                 entidades con nombres claros (Articulo, SaldoPartida, Pedido...)
    servicio.py                puerta única hacia Tango, con caché
  web/
    servidor.py                API propia + panel + páginas
    estatico/                  panel de la PC y páginas para el celular
  config.py                    config.ini
  credenciales.py              token de Tango cifrado (DPAPI)
  actualizador.py              actualización automática desde los Releases
  contexto.py                  estado del programa y acciones del panel
  sistema.py                   Windows: inicio automático, avisos, red
  app.py                       arranque
tests/                         pruebas (sin Tango real)
```

Para agregar algo nuevo: el dato se pide a `ServicioTango`, nunca directo a la API de Tango. Si Tango no lo trae todavía, se agrega primero el proceso en `procesos.py`, el modelo en `modelos.py` y el método en `servicio.py`.

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
| `/api/ventas?desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Renglones de comprobantes de venta (máx. 366 días) |

## Cómo se genera el .exe

Cada vez que se sube un cambio a `main`, GitHub Actions corre las pruebas, genera `HerramientaTango.exe` en una máquina Windows y lo publica en **Releases** con un número de versión nuevo.

- Última versión: pestaña **Releases**, archivo `HerramientaTango.zip` (trae el `.exe` y este README). El release también publica el `.exe` suelto y su `.sha256`, que usa el actualizador.
- Para generar de nuevo sin cambiar código: **Actions** > "Generar exe" > **Run workflow**.

Si el antivirus marca el .exe como sospechoso (pasa a veces con los .exe hechos con PyInstaller), hay que agregarlo como excepción.

## Instalarlo en la PC de la oficina

1. Descomprimí el zip en una carpeta fija, por ejemplo `C:\HerramientaTango`, y abrí `HerramientaTango.exe`. No abre ninguna ventana negra: se abre el **panel** en el navegador.
2. La primera vez, el panel pide dos datos y los prueba contra Tango antes de guardarlos:
   - **Dirección del servidor de Tango**: la que se ve en el navegador al abrir el Tango web (se puede pegar entera).
   - **Token de Tango**: en el Tango web, menú de usuario > Desarrollador > Generar > **Aceptar**.
   - Dejá marcada la opción **Abrir el programa solo al prender la PC**.
3. Si Windows pregunta si permite el acceso a la red, elegí **Permitir** (si la red figura como "Pública", marcá también esa opción).
4. En el panel aparece un **código QR**: se escanea con el celular (conectado al Wi-Fi de la oficina) y abre la consulta de stock.

Si se vuelve a abrir el `.exe` con el programa ya funcionando, solo abre el panel. El panel (`http://127.0.0.1:8085/panel`) solo funciona desde la misma PC: desde otro equipo no se puede cambiar la configuración.

Junto al .exe se crean (y **no** se suben al repositorio):
- `config.ini`: ajustes finos (puerto, actualizaciones). La empresa viene fija en 3.
- `token.dat`: el token de Tango **cifrado**. Solo lo puede leer el mismo usuario de Windows en la misma PC.
- `herramienta_tango.log`: registro, por si algo falla.

## Actualizaciones automáticas

El programa se actualiza solo. Cada 15 minutos consulta los Releases de este repositorio y, si hay una versión nueva:

1. Descarga `HerramientaTango.exe` y verifica su SHA-256 contra `HerramientaTango.exe.sha256`. Si no coincide, no instala nada.
2. Aparta el `.exe` en uso como `HerramientaTango.old.exe` y pone el nuevo en su lugar. Si algo falla, vuelve todo como estaba.
3. Se reinicia con la versión nueva (se abre una ventana nueva y se cierra la vieja). El corte dura unos segundos.

La página del celular muestra un aviso mientras se instala y se recarga sola con la versión nueva. `config.ini` y `token.dat` no se tocan.

En `config.ini`, sección `[actualizaciones]`: `automatica = no` hace que solo avise sin instalar, y `cada_minutos` cambia la frecuencia. La PC necesita salida a internet hacia github.com.

Antes de publicar cada versión, el workflow prueba en Windows la actualización de punta a punta: arranca el `.exe`, le anuncia una versión nueva y verifica que se reemplace, se reinicie y vuelva a responder.

Ojo: cualquiera con permiso de escritura en este repositorio puede publicar una versión que la PC de la oficina va a instalar sola. Conviene tener activada la verificación en dos pasos en las cuentas de GitHub que tienen acceso.

### Primera instalación o actualización a mano

Cerrá el programa, reemplazá el `.exe` por el de la última versión y abrilo. No borres `config.ini` ni `token.dat`.

## Si algo falla

| Lo que se ve | Qué hacer |
|---|---|
| El panel dice "Tango rechazó el token" | Generá un token nuevo en Tango (Desarrollador > Generar > Aceptar) y cargalo en Ajustes > Servidor y token. |
| El panel dice "Sin conexión con Tango" | Revisá que el servidor de Tango esté prendido y la dirección en Ajustes > Servidor y token. |
| El celular no abre la página | El celular tiene que estar en el Wi-Fi de la oficina. Revisá el permiso del firewall. Si el panel muestra otras direcciones, probá con esas. |
| Aviso "el puerto 8085 está ocupado" | Otro programa usa ese puerto: cambiá `puerto` en `config.ini`. |
| Algo no funciona y no se ve por qué | Mirá `herramienta_tango.log` en la carpeta del programa. |

## Límites actuales

- Stock por partida muestra solo artículos que llevan partidas.
- No hay escritura en Tango.
- Funciona solo dentro de la red de la oficina, a propósito: el token de Tango viaja sin cifrar y la API propia no pide clave.

## Desarrollo

```
python -m unittest discover -s tests      # pruebas
python HerramientaTango.py                # correrlo sin generar el .exe (abre el panel)
```

Solo usa la librería estándar de Python 3.10 o superior.
