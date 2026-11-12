# Arma el paquete de Herramienta Tango para Windows, sin .exe propio:
#
#   dist\HerramientaTango\
#     Abrir Herramienta Tango.cmd   abre el programa (la primera vez crea los accesos directos)
#     README.md
#     python\                        Python oficial embebido (pythonw.exe firmado por la PSF)
#     app\                           codigo del programa
#
#   dist\HerramientaTango.zip              todo, para la primera instalacion
#   dist\HerramientaTango-app.zip          solo app\, lo que baja el actualizador
#   dist\HerramientaTango-app.zip.sha256   para que el actualizador verifique la descarga
#
# Uso: ./scripts/armar_paquete.ps1 -PythonVersion 3.12.10
param([string]$PythonVersion = '3.12.10')
$ErrorActionPreference = 'Stop'

$dist = Join-Path (Get-Location) 'dist'
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
$raiz = Join-Path $dist 'HerramientaTango'
New-Item -ItemType Directory -Force (Join-Path $raiz 'python'), (Join-Path $raiz 'app') | Out-Null

# --- Python oficial embebido ---------------------------------------------------
$zipPython = Join-Path ([IO.Path]::GetTempPath()) "python-$PythonVersion-embed-amd64.zip"
Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $zipPython
Expand-Archive $zipPython (Join-Path $raiz 'python')

foreach ($exe in 'python.exe', 'pythonw.exe') {
    $firma = Get-AuthenticodeSignature (Join-Path $raiz "python\$exe")
    if ($firma.Status -ne 'Valid' -or $firma.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        throw "$exe no tiene una firma valida de la Python Software Foundation ($($firma.Status))"
    }
    Write-Output "$exe firmado por: $($firma.SignerCertificate.Subject)"
}

# El Python embebido solo busca modulos donde dice su archivo ._pth: se agrega la carpeta app
$pth = Get-ChildItem (Join-Path $raiz 'python') -Filter 'python*._pth' | Select-Object -First 1
Add-Content $pth.FullName "`r`n..\app" -Encoding ascii

# --- Codigo ------------------------------------------------------------------------
$app = Join-Path $raiz 'app'
Copy-Item HerramientaTango.pyw $app
Copy-Item -Recurse herramienta_tango (Join-Path $app 'herramienta_tango')
Copy-Item -Recurse recursos (Join-Path $app 'recursos')
Get-ChildItem $app -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

# --- Lanzador y README -------------------------------------------------------------
$lanzador = "@echo off`r`nstart `"`" `"%~dp0python\pythonw.exe`" `"%~dp0app\HerramientaTango.pyw`"`r`n"
[IO.File]::WriteAllText((Join-Path $raiz 'Abrir Herramienta Tango.cmd'), $lanzador, [Text.Encoding]::ASCII)
Copy-Item README.md $raiz

# --- Zips ----------------------------------------------------------------------------
$zipApp = Join-Path $dist 'HerramientaTango-app.zip'
python scripts/comprimir.py $app $zipApp
if ($LASTEXITCODE -ne 0) { throw 'No se pudo armar el zip de codigo' }
$hash = (Get-FileHash $zipApp -Algorithm SHA256).Hash.ToLower()
[IO.File]::WriteAllText("$zipApp.sha256", "$hash  HerramientaTango-app.zip", [Text.Encoding]::ASCII)
python scripts/comprimir.py $raiz (Join-Path $dist 'HerramientaTango.zip') --incluir-carpeta
if ($LASTEXITCODE -ne 0) { throw 'No se pudo armar el zip completo' }

Get-ChildItem $dist -File | Format-Table Name, Length | Out-String | Write-Output
Write-Output "SHA-256 del paquete de codigo: $hash"
