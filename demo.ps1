# FIRETRACE demo launcher (PowerShell)
#
#   .\demo.ps1              live feed when available, archive when not
#   .\demo.ps1 -Offline     force the offline archive
#
# Thin wrapper: all the real logic is in scripts/demo.mjs so the bash, PowerShell
# and npm entry points cannot drift apart.

param([switch]$Offline)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

Write-Host ''
Write-Host '  FIRETRACE' -ForegroundColor Yellow -NoNewline
Write-Host '  starting demo' -ForegroundColor DarkGray
Write-Host ''

$node = Get-Command node -ErrorAction SilentlyContinue
if ($null -eq $node) {
    Write-Host '  x Node.js 18+ was not found on PATH.' -ForegroundColor Red
    Write-Host '    Install it from https://nodejs.org and run this again.' -ForegroundColor DarkGray
    exit 1
}

if ($Offline) { node --no-deprecation scripts/demo.mjs --offline }
else { node --no-deprecation scripts/demo.mjs }
exit $LASTEXITCODE
