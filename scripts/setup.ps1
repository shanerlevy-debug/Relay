# Relay — one-time local setup.
# Creates a venv at .venv\ and installs dependencies from requirements.txt.
# Re-run any time requirements.txt changes.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPath = Join-Path $Root '.venv'

if (-not (Test-Path $VenvPath)) {
    Write-Host "Creating venv at $VenvPath"
    python -m venv $VenvPath
} else {
    Write-Host "Reusing existing venv at $VenvPath"
}

$Pip = Join-Path $VenvPath 'Scripts\pip.exe'
& $Pip install --upgrade pip
& $Pip install -r (Join-Path $Root 'requirements.txt')

Write-Host ""
Write-Host "Setup complete. Next steps:"
Write-Host "  1. copy .env.example .env       # then edit .env with your tokens"
Write-Host "  2. copy agents.yaml.example agents.yaml   # then edit with your agent_ids"
Write-Host "  3. .\scripts\run-bridge.ps1"
