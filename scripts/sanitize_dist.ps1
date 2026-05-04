$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

if (-not (Test-Path dist)) {
  throw "dist folder was not found. Run scripts\build_windows.ps1 first."
}

New-Item -ItemType Directory -Path dist\config -Force | Out-Null
Copy-Item config\config.example.yaml dist\config\config.yaml -Force

Write-Host "Sanitized dist runtime config: $Root\dist\config\config.yaml"
