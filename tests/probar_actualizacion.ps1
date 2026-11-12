# Prueba de punta a punta en Windows del paquete armado en dist\:
#   1. El programa arranca con el Python oficial (pythonw.exe) y responde.
#   2. Crea los accesos directos desde el panel.
#   3. Ante una version nueva (GitHub falso) descarga el codigo, reemplaza la
#      carpeta app, se reinicia y vuelve a responder.
$ErrorActionPreference = 'Stop'

$dir = Join-Path $env:RUNNER_TEMP 'prueba_instalacion'
if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
Copy-Item -Recurse dist\HerramientaTango $dir
@"
[tango]
servidor = http://127.0.0.1:9
company = 3
timeout_segundos = 5
[programa]
puerto = 8099
vigencia_saldos_segundos = 60
[actualizaciones]
repositorio = prueba/prueba
automatica = si
cada_minutos = 5
"@ | Set-Content (Join-Path $dir 'config.ini') -Encoding utf8

$logFalso = Join-Path $dir 'github_falso.log'
Start-Process python -ArgumentList 'tests\servidor_releases_falso.py', 'dist\HerramientaTango-app.zip', '8765', $logFalso -WindowStyle Hidden
Start-Sleep 2

$env:HERRAMIENTA_TANGO_TOKEN = '00000000-0000-0000-0000-000000000000'
$env:HERRAMIENTA_TANGO_URL_RELEASES = 'http://127.0.0.1:8765/releases/latest'
Start-Process (Join-Path $dir 'python\pythonw.exe') -ArgumentList "`"$(Join-Path $dir 'app\HerramientaTango.pyw')`"", '--no-abrir' -WorkingDirectory $dir

$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep 2
    try {
        $e = Invoke-RestMethod 'http://127.0.0.1:8099/api/estado' -TimeoutSec 3
        $pedidos = if (Test-Path $logFalso) { Get-Content $logFalso } else { @() }
        $descargas = @($pedidos | Where-Object { $_ -eq '/paquete' }).Count
        $consultas = @($pedidos | Where-Object { $_ -eq '/releases/latest' }).Count
        Write-Output "intento $i : estado=$($e.actualizacion.estado) consultas=$consultas descargas=$descargas"
        if ($descargas -eq 1 -and $consultas -ge 2 -and $e.actualizacion.estado -eq 'al_dia') { $ok = $true; break }
    } catch {
        Write-Output "intento $i : el programa no responde (puede estar reiniciando)"
    }
}

# Accesos directos (accion del panel, desde la misma PC)
$r = Invoke-RestMethod 'http://127.0.0.1:8099/api/sistema/accesos-directos' -Method Post -Body '{}' `
     -ContentType 'application/json' -Headers @{ 'X-Herramienta-Tango' = '1' }
Write-Output "Accesos directos: $($r.mensaje)"
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Herramienta Tango.lnk'
$hayAcceso = Test-Path $lnk

$sistema = Invoke-RestMethod 'http://127.0.0.1:8099/api/sistema'
Write-Output "Inicio automatico disponible: $($sistema.inicio_automatico_disponible)"

Start-Sleep 3
Get-ChildItem $dir | Format-Table Name, Mode | Out-String | Write-Output
if (Test-Path (Join-Path $dir 'herramienta_tango.log')) { Get-Content (Join-Path $dir 'herramienta_tango.log') | Write-Output }

Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process -Force
if (-not $ok) { throw 'La actualizacion automatica no funciono' }
if (-not $hayAcceso) { throw 'No se creo el acceso directo en el escritorio' }
if (-not $sistema.inicio_automatico_disponible) { throw 'El programa no detecto que esta instalado' }
if (-not (Test-Path (Join-Path $dir 'app\HerramientaTango.pyw'))) { throw 'Falta app\HerramientaTango.pyw despues de actualizar' }
if (Test-Path (Join-Path $dir 'app.old')) { Write-Warning 'Quedo app.old (se borra en el proximo arranque)' }
Write-Output 'Instalacion, accesos directos y actualizacion automatica OK'
