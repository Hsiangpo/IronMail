$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path config\config.yaml)) {
  Copy-Item config\config.example.yaml config\config.yaml -Force
  Write-Host "已根据 config\config.example.yaml 创建本地配置: config\config.yaml"
}

.\.venv\Scripts\pyinstaller.exe `
  --clean `
  --onefile `
  --console `
  --paths src `
  --name IronMail `
  send_emails.py

New-Item -ItemType Directory -Path dist\config -Force | Out-Null
Copy-Item config\config.yaml dist\config\config.yaml -Force
New-Item -ItemType Directory -Path dist\Mails -Force | Out-Null
Copy-Item Mails\* dist\Mails\ -Recurse -Force
New-Item -ItemType Directory -Path dist\logs -Force | Out-Null

Write-Host "打包完成: $Root\dist\IronMail.exe"
Write-Host "运行前请确认 dist\config\config.yaml 里的发件邮箱已配置。"
