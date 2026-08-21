# One command setup for Windows.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# Checks what is missing, writes a starter .env if there is none, pulls the
# model, builds the containers and waits until the site answers.

$ErrorActionPreference = "Stop"
function Ok($m)   { Write-Host "  ok   $m" -ForegroundColor Green }
function Warn($m) { Write-Host " warn  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host " fail  $m" -ForegroundColor Red; exit 1 }
function Step($m) { Write-Host ""; Write-Host $m -ForegroundColor White }

Set-Location (Split-Path $PSScriptRoot -Parent)

Step "Checking what is installed"

try { docker info *> $null; Ok "docker is running" }
catch { Fail "Docker is not running. Install Docker Desktop, start it, then run this again." }

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
  $guess = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
  if (Test-Path $guess) { $ollama = $guess } else {
    Fail "Ollama is not installed. Get it from https://ollama.com/download then run this again."
  }
} else { $ollama = $ollama.Source }
Ok "ollama is installed"

try { Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 5 *> $null }
catch {
  Warn "ollama is not answering, starting it"
  Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
  Start-Sleep -Seconds 6
}
try { Invoke-RestMethod -Uri "http://localhost:11434/api/version" -TimeoutSec 5 *> $null; Ok "ollama is answering" }
catch { Fail "ollama did not start" }

Step "Configuration"
if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  $bytes = New-Object byte[] 16
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $pass = ([Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', '').Substring(0, 16)
  (Get-Content ".env") -replace '^NEO4J_PASSWORD=.*', "NEO4J_PASSWORD=$pass" | Set-Content ".env"
  Ok "wrote .env with a generated database password"
  Warn "Telegram is off until you add TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_ID"
} else {
  Ok ".env already exists, leaving it alone"
}

$env_lines = Get-Content ".env" | Where-Object { $_ -match '^\s*[A-Z_]+=' }
$settings = @{}
foreach ($line in $env_lines) {
  $parts = $line -split '=', 2
  $settings[$parts[0].Trim()] = $parts[1].Trim()
}
$model = if ($settings["LLM_MODEL"]) { $settings["LLM_MODEL"] } else { "qwen2.5:3b-instruct" }
$port  = if ($settings["WEB_PORT"])  { $settings["WEB_PORT"] }  else { "3000" }

$installed = & $ollama list 2>$null | ForEach-Object { ($_ -split '\s+')[0] }
if ($installed -contains $model) {
  Ok "model $model is present"
} else {
  Step "Downloading the model, this takes a few minutes"
  & $ollama pull $model
  if ($LASTEXITCODE -ne 0) { Fail "could not pull $model" }
}

Step "Building and starting"
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail "build failed" }

Step "Waiting for the site"
$up = $false
foreach ($i in 1..60) {
  try {
    Invoke-WebRequest -Uri "http://localhost:$port" -TimeoutSec 5 -UseBasicParsing *> $null
    $up = $true; break
  } catch { Start-Sleep -Seconds 5 }
}
if (-not $up) { Fail "site did not come up. check: docker compose logs web" }
Ok "site is answering"

Write-Host ""
Write-Host "Ready."
Write-Host "  site    http://localhost:$port"
Write-Host "  status  http://localhost:$port/status"
Write-Host "  logs    docker compose logs -f agents"
Write-Host ""
Write-Host "It starts collecting on its own. The first links appear within a few minutes."
