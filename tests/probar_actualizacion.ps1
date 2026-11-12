# Prueba de punta a punta de la actualizacion automatica, en Windows.
# Arranca el .exe, le anuncia una version nueva desde un GitHub falso y
# verifica que se reemplaza a si mismo, se reinicia y vuelve a responder.
$ErrorActionPreference = 'Stop'

$dir = Join-Path $env:RUNNER_TEMP 'prueba_actualizacion'
New-Item -ItemType Directory -Force $dir | Out-Null
Copy-Item dist\HerramientaTango.exe (Join-Path $dir 'HerramientaTango.exe')
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
Start-Process python -ArgumentList 'tests\servidor_releases_falso.py', 'dist\HerramientaTango.exe', '8765', $logFalso -WindowStyle Hidden
Start-Sleep 2

$env:HERRAMIENTA_TANGO_TOKEN = '00000000-0000-0000-0000-000000000000'
$env:HERRAMIENTA_TANGO_URL_RELEASES = 'http://127.0.0.1:8765/releases/latest'
Start-Process (Join-Path $dir 'HerramientaTango.exe') -ArgumentList '--no-abrir' -WorkingDirectory $dir

# Esperar: descarga del exe nuevo, reinicio y segunda consulta (queda "al dia")
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep 2
    try {
        $e = Invoke-RestMethod 'http://127.0.0.1:8099/api/estado' -TimeoutSec 3
        $pedidos = if (Test-Path $logFalso) { Get-Content $logFalso } else { @() }
        $descargas = @($pedidos | Where-Object { $_ -eq '/exe' }).Count
        $consultas = @($pedidos | Where-Object { $_ -eq '/releases/latest' }).Count
        Write-Output "intento $i : estado=$($e.actualizacion.estado) consultas=$consultas descargas=$descargas"
        if ($descargas -eq 1 -and $consultas -ge 2 -and $e.actualizacion.estado -eq 'al_dia') { $ok = $true; break }
    } catch {
        Write-Output "intento $i : el programa no responde (puede estar reiniciando)"
    }
}

Get-ChildItem $dir | Format-Table Name, Length | Out-String | Write-Output
if (Test-Path (Join-Path $dir 'herramienta_tango.log')) { Get-Content (Join-Path $dir 'herramienta_tango.log') | Write-Output }

Get-Process HerramientaTango -ErrorAction SilentlyContinue | Stop-Process -Force
if (-not $ok) { throw 'La actualizacion automatica no funciono' }

# El .old.exe tiene que haberse borrado al arrancar la version nueva
Start-Sleep 2
if (Test-Path (Join-Path $dir 'HerramientaTango.old.exe')) { Write-Warning 'Quedo el .old.exe (se borra en el proximo arranque)' }
Write-Output 'Actualizacion automatica OK'
