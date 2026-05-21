# Relay — run the bridge locally on Windows.
# Activates the venv at .venv\ and runs bridge.py in the foreground.
# Ctrl+C to stop.
#
# bridge.py uses python-dotenv to load .env automatically, so this wrapper
# does not need to inject env vars itself.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    Write-Host "Venv not found. Run .\scripts\setup.ps1 first."
    exit 1
}

if (-not (Test-Path (Join-Path $Root '.env'))) {
    Write-Host ".env not found. Copy .env.example to .env and fill in your tokens."
    exit 1
}

if (-not (Test-Path (Join-Path $Root 'agents.yaml'))) {
    Write-Host "agents.yaml not found. Copy agents.yaml.example to agents.yaml and fill in agent_ids."
    exit 1
}

& $VenvPython bridge.py
