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
    servidor.py                API propia + páginas
    estatico/                  páginas para el celular
  config.py                    config.ini
  credenciales.py              token de Tango cifrado (DPAPI)
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

- Última versión: pestaña **Releases**, archivo `HerramientaTango.zip` (trae el `.exe` y este README).
- Para generar de nuevo sin cambiar código: **Actions** > "Generar exe" > **Run workflow**.

Si el antivirus marca el .exe como sospechoso (pasa a veces con los .exe hechos con PyInstaller), hay que agregarlo como excepción.

## Instalarlo en la PC de la oficina

1. Descomprimí el zip en una carpeta fija, por ejemplo `C:\HerramientaTango`.
2. Abrí `HerramientaTango.exe`. La primera vez te pide tres datos y los guarda:
   - **Dirección del servidor de Tango**: la misma que se ve en el navegador al abrir el Tango web (por ejemplo `http://NOMBRE-PC:17000`).
   - **Número de empresa**: aparece en la dirección del Tango web, `.../company/NUMERO/...`.
   - **Token de Tango**: se genera en el Tango web, menú de usuario > Desarrollador > Generar > **Aceptar**.
3. La primera vez, Windows pregunta si permite el acceso a la red: elegí **Permitir**. Si la red de la oficina figura como "Pública", marcá también esa opción.
4. La ventana muestra las direcciones para abrir desde el celular, por ejemplo `http://192.168.0.20:8085`. Guardala como acceso directo en la pantalla de inicio del celular.

Para que arranque solo al prender la PC: Windows + R, `shell:startup`, y pegá ahí un acceso directo al .exe.

Junto al .exe se crean (y **no** se suben al repositorio):
- `config.ini`: servidor de Tango, empresa, puerto. Se edita con el Bloc de notas.
- `token.dat`: el token de Tango **cifrado**. Solo lo puede leer el mismo usuario de Windows en la misma PC.
- `herramienta_tango.log`: registro, por si algo falla.

## Actualizar a una versión nueva

Cerrá el programa, reemplazá el `.exe` por el de la última versión y abrilo. No borres `config.ini` ni `token.dat`.

## Si algo falla

| Lo que se ve | Qué hacer |
|---|---|
| "Tango rechazó el token (401)" | Borrá `token.dat`, abrí el programa y pegá un token aceptado en Tango. |
| "No se pudo conectar con Tango" | Revisá que el servidor de Tango esté prendido y que `servidor` en `config.ini` sea correcto. |
| El celular no abre la página | El celular tiene que estar en el Wi-Fi de la oficina. Revisá el permiso del firewall. |
| "No se pudo abrir el puerto 8085" | El programa ya está abierto en otra ventana, o cambiá `puerto` en `config.ini`. |

## Límites actuales

- Stock por partida muestra solo artículos que llevan partidas.
- No hay escritura en Tango.
- Funciona solo dentro de la red de la oficina, a propósito: el token de Tango viaja sin cifrar y la API propia no pide clave.

## Desarrollo

```
python -m unittest discover -s tests      # pruebas
python HerramientaTango.py --no-abrir     # correrlo sin generar el .exe
```

Solo usa la librería estándar de Python 3.10 o superior.
