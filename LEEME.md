# Consulta de stock Sianco

Programa que muestra en el celular el stock por partida que tiene Tango. **Solo lee**: no carga ni modifica nada en Tango.

Corre en una PC de la oficina que quede prendida. Gustavo lo abre desde el celular, conectado al Wi-Fi de la oficina.

## Cómo se genera el .exe

No hace falta instalar Python en ningún lado. Cada vez que se sube un cambio a la rama `main`, GitHub Actions genera el `.exe` en una máquina Windows y lo publica en **Releases**, con un número de versión nuevo (1.1, 1.2, ...).

- Última versión: pestaña **Releases** del repositorio, archivo `ConsultaStockSianco.zip` (trae el `.exe` y este LEEME).
- Para generar de nuevo sin cambiar código: pestaña **Actions** > "Generar exe" > **Run workflow**.
- El número de versión aparece en la ventana del programa al arrancar.

## Qué hay en el repositorio

| Archivo | Para qué |
|---|---|
| `consulta_stock.py` | El programa |
| `web/index.html` | La página que ve el celular (va adentro del .exe) |
| `.github/workflows/generar-exe.yml` | Las instrucciones para que GitHub genere el .exe |
| `LEEME.md` | Estas instrucciones |

Al arrancar por primera vez, el programa crea junto al .exe (y **no** se suben al repositorio):
- `config.ini`: servidor de Tango, empresa, puerto. Se puede editar con el Bloc de notas.
- `token.dat`: el token de Tango **cifrado**. Solo lo puede leer el mismo usuario de Windows en la misma PC.
- `consulta_stock.log`: registro de lo que pasa, por si algo falla.

Si el antivirus marca el .exe como sospechoso (pasa a veces con los .exe hechos con PyInstaller), hay que agregarlo como excepción.

## Instalarlo en la PC de la oficina

1. Descomprimí el zip de la última versión en una carpeta fija, por ejemplo `C:\ConsultaStock`.
2. Abrilo con doble clic. Te va a pedir el token de Tango: pegalo y apretá Enter.
   - El token se genera en el Tango web: menú de usuario > Desarrollador > Generar > **Aceptar**.
3. La primera vez, Windows pregunta si permite el acceso a la red: elegí **Permitir**. Si la red de la oficina figura como "Pública", marcá también esa opción, o el celular no va a poder entrar.
4. La ventana muestra las direcciones para abrir desde el celular, por ejemplo `http://192.168.0.20:8085`. Probá en el celular de Gustavo y guardala como acceso directo en la pantalla de inicio.

Para que arranque solo al prender la PC: apretá Windows + R, escribí `shell:startup` y pegá ahí un acceso directo al .exe.

## Uso diario

- La ventana del programa tiene que quedar abierta (se puede minimizar).
- Los datos se renuevan solos cada minuto. El botón **Actualizar** de la página los pide en el momento.

## Si algo falla

| Lo que se ve | Qué hacer |
|---|---|
| "Tango rechazó el token (401)" | Borrá `token.dat`, abrí el programa de nuevo y pegá un token aceptado en Tango. |
| "No se pudo conectar con Tango" | Revisá que el servidor de Tango esté prendido y que `servidor` en `config.ini` sea correcto. |
| El celular no abre la página | El celular tiene que estar en el Wi-Fi de la oficina. Revisá el permiso del firewall (paso 3 de la instalación). |
| "No se pudo abrir el puerto 8085" | El programa ya está abierto en otra ventana, o cambiá `puerto` en `config.ini`. |

## Límites de esta versión

- Muestra solo artículos que llevan partidas. Los que no llevan partidas todavía no aparecen.
- No carga movimientos: es solo para consultar.
- Funciona solo dentro de la red de la oficina, a propósito: el token de Tango viaja sin cifrar, así que no conviene abrirlo a internet.

## Actualizar a una versión nueva

1. Cerrá la ventana del programa.
2. Reemplazá el `.exe` por el de la última versión. No borres `config.ini` ni `token.dat`: así no hay que volver a cargar el token.
3. Abrilo de nuevo.
