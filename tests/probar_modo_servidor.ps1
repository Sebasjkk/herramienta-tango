# Prueba de punta a punta en Windows del modo servidor, con el paquete armado en dist\:
#   1. Una copia comun activa el modo servidor desde el panel (pide permiso de
#      administrador: en GitHub Actions se da solo).
#   2. Queda la tarea programada y la regla del firewall, la copia comun se cierra
#      y arranca la del servidor con la cuenta SYSTEM.
#   3. La copia del servidor lee el token (cifrado a nivel equipo).
#   4. Si el programa se cae, el vigilante lo vuelve a abrir.
#   5. Desactivar borra la tarea, la regla y la marca, y el programa se cierra.
$ErrorActionPreference = 'Stop'
$puerto = 8098
$base = "http://127.0.0.1:$puerto"
$encabezados = @{ 'X-Herramienta-Tango' = '1' }

$dir = Join-Path $env:RUNNER_TEMP 'prueba_servidor'
if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
Copy-Item -Recurse dist\HerramientaTango $dir
@"
[tango]
servidor = http://127.0.0.1:9
company = 3
timeout_segundos = 5
[programa]
puerto = $puerto
vigencia_saldos_segundos = 60
[actualizaciones]
repositorio =
automatica = no
cada_minutos = 15
"@ | Set-Content (Join-Path $dir 'config.ini') -Encoding utf8

# Token guardado como lo guarda el panel (sin variable de entorno: la cuenta SYSTEM no la ve)
Remove-Item Env:HERRAMIENTA_TANGO_TOKEN -ErrorAction SilentlyContinue
Push-Location $dir
& .\python\python.exe -c "from herramienta_tango import credenciales; credenciales.guardar_token('00000000-0000-0000-0000-000000000000')"
Pop-Location
if (-not (Test-Path (Join-Path $dir 'token.dat'))) { throw 'No se guardo token.dat' }

function Esperar([scriptblock]$condicion, [int]$segundos, [string]$que) {
    for ($i = 0; $i -lt $segundos; $i += 2) {
        Start-Sleep 2
        try { if (& $condicion) { Write-Output "OK: $que"; return } } catch { }
    }
    if (Test-Path (Join-Path $dir 'herramienta_tango.log')) { Get-Content (Join-Path $dir 'herramienta_tango.log') | Write-Output }
    if (Test-Path (Join-Path $dir 'modo_servidor_error.txt')) { Get-Content (Join-Path $dir 'modo_servidor_error.txt') | Write-Output }
    throw "No paso: $que"
}

function Sistema { Invoke-RestMethod "$base/api/sistema" -TimeoutSec 3 }

try {
    # 1. Copia comun
    Start-Process (Join-Path $dir 'python\pythonw.exe') -ArgumentList "`"$(Join-Path $dir 'app\HerramientaTango.pyw')`"", '--no-abrir' -WorkingDirectory $dir
    Esperar { (Sistema).configurado } 30 'arranca la copia comun'
    $s = Sistema
    if ($s.modo_servidor.como_servicio) { throw 'La copia comun dice que es la del servidor' }

    # 2. Activar desde el panel
    $r = Invoke-RestMethod "$base/api/sistema/modo-servidor" -Method Post -Body '{"activo":true}' `
         -ContentType 'application/json' -Headers $encabezados
    Write-Output "Activar: $($r.mensaje)"
    Esperar { $x = Sistema; $x.modo_servidor.como_servicio -and $x.modo_servidor.activo } 120 'arranca la copia del servidor'

    # 3. La copia del servidor leyo el token
    $s = Sistema
    if (-not $s.configurado) { throw 'La copia del servidor no pudo leer el token' }
    $tarea = Get-ScheduledTask -TaskName 'Herramienta Tango'
    if ($tarea.Principal.UserId -notmatch 'SYSTEM') { throw "La tarea no corre como SYSTEM: $($tarea.Principal.UserId)" }
    if (-not (Get-NetFirewallRule -DisplayName 'Herramienta Tango' -ErrorAction SilentlyContinue)) { throw 'Falta la regla del firewall' }
    $hijo = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*--hijo-servicio*' }
    $duenio = ($hijo | Select-Object -First 1 | Invoke-CimMethod -MethodName GetOwner).User
    Write-Output "El programa corre con la cuenta: $duenio"
    if ($duenio -ne 'SYSTEM') { throw "El programa no corre como SYSTEM: $duenio" }

    # 4. Se cae y vuelve
    $hijo | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
    Start-Sleep 3
    Esperar { (Sistema).modo_servidor.como_servicio } 60 'el vigilante lo vuelve a abrir'

    # 5. Desactivar
    $r = Invoke-RestMethod "$base/api/sistema/modo-servidor" -Method Post -Body '{"activo":false}' `
         -ContentType 'application/json' -Headers $encabezados
    Write-Output "Desactivar: $($r.mensaje)"
    Esperar { try { Sistema | Out-Null; $false } catch { $true } } 30 'el programa se cierra'
    Start-Sleep 12
    if (Get-ScheduledTask -TaskName 'Herramienta Tango' -ErrorAction SilentlyContinue) { throw 'Quedo la tarea programada' }
    if (Get-NetFirewallRule -DisplayName 'Herramienta Tango' -ErrorAction SilentlyContinue) { throw 'Quedo la regla del firewall' }
    if (Test-Path (Join-Path $dir 'modo_servidor.txt')) { throw 'Quedo la marca del modo servidor' }
    $sigue = $true
    try { Sistema | Out-Null } catch { $sigue = $false }
    if ($sigue) { throw 'El vigilante lo volvio a abrir despues de desactivar' }
    Write-Output 'Modo servidor OK'
}
finally {
    Get-Content (Join-Path $dir 'herramienta_tango.log') -ErrorAction SilentlyContinue | Write-Output
    Unregister-ScheduledTask -TaskName 'Herramienta Tango' -Confirm:$false -ErrorAction SilentlyContinue
    Get-NetFirewallRule -DisplayName 'Herramienta Tango' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Get-Process pythonw -ErrorAction SilentlyContinue | Stop-Process -Force
}
