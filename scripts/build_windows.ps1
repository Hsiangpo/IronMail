$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

function Resolve-Python {
  if ($env:IRONMAIL_PYTHON) {
    if (-not (Test-Path $env:IRONMAIL_PYTHON)) {
      throw "IRONMAIL_PYTHON points to a missing file: $env:IRONMAIL_PYTHON"
    }
    return @($env:IRONMAIL_PYTHON)
  }

  $Candidates = @(
    @{ Command = "py"; Args = @("-3.12") },
    @{ Command = "py"; Args = @("-3.11") },
    @{ Command = "py"; Args = @("-3") },
    @{ Command = "python"; Args = @() },
    @{ Command = "python3"; Args = @() }
  )

  foreach ($Candidate in $Candidates) {
    if (-not (Get-Command $Candidate.Command -ErrorAction SilentlyContinue)) {
      continue
    }
    & $Candidate.Command @($Candidate.Args) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
      return @($Candidate.Command) + @($Candidate.Args)
    }
  }

  throw "Python 3.10 or newer was not found. Install Python or set IRONMAIL_PYTHON to python.exe."
}

$Python = @(Resolve-Python)
$PythonCommand = $Python[0]
$PythonArgs = @()
if ($Python.Length -gt 1) {
  $PythonArgs = $Python[1..($Python.Length - 1)]
}

& $PythonCommand @PythonArgs -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

if (-not (Test-Path config\config.yaml)) {
  Copy-Item config\config.example.yaml config\config.yaml -Force
  Write-Host "Created local config from config\config.example.yaml: config\config.yaml"
}

.\.venv\Scripts\pyinstaller.exe `
  --clean `
  --onefile `
  --windowed `
  --paths src `
  --name IronMail `
  send_emails.py
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

New-Item -ItemType Directory -Path dist\config -Force | Out-Null
Copy-Item config\config.yaml dist\config\config.yaml -Force
if (Test-Path dist\Mails) {
  Remove-Item -LiteralPath dist\Mails -Recurse -Force
}
New-Item -ItemType Directory -Path dist\Mails -Force | Out-Null
Copy-Item Mails\* dist\Mails\ -Recurse -Force

$RecipientDirName = [string]::Concat([char[]](0x6536, 0x4ef6, 0x540d, 0x5355))
$LegacyRecipientDirNames = @(
  [string]::Concat([char[]](0x6536, 0x4ef6, 0x4eba, 0x540d, 0x5355)),
  [string]::Concat([char[]](0x53d1, 0x4ef6, 0x5bf9, 0x8c61))
)
$PreferredRecipientDir = Join-Path "dist\Mails" $RecipientDirName
if (-not (Test-Path $PreferredRecipientDir)) {
  foreach ($LegacyRecipientDirName in $LegacyRecipientDirNames) {
    $LegacyRecipientDir = Join-Path "dist\Mails" $LegacyRecipientDirName
    if (Test-Path $LegacyRecipientDir) {
      Rename-Item -LiteralPath $LegacyRecipientDir -NewName $RecipientDirName
      break
    }
  }
}
New-Item -ItemType Directory -Path $PreferredRecipientDir -Force | Out-Null

if (Test-Path dist\logs) {
  Remove-Item -LiteralPath dist\logs -Recurse -Force
}
New-Item -ItemType Directory -Path dist\logs -Force | Out-Null

Write-Host "Build completed: $Root\dist\IronMail.exe"
Write-Host "Before running, check sender settings in dist\config\config.yaml."
