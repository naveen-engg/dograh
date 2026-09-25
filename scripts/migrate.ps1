#!/usr/bin/env pwsh
# Run Alembic database migrations (Windows)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BaseDir   = Split-Path -Parent $ScriptDir
Set-Location $BaseDir

$PipecatSrc = Join-Path $BaseDir 'pipecat/src'
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$BaseDir;$PipecatSrc;$($env:PYTHONPATH)"
} else {
    $env:PYTHONPATH = "$BaseDir;$PipecatSrc"
}

$EnvFile = Join-Path $BaseDir 'api/.env'

# Load environment variables
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#')) {
            $parts = $line -split '=', 2
            if ($parts.Count -eq 2) {
                [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim().Trim('"'), 'Process')
            }
        }
    }
} else {
    Write-Host "Error: Environment file $EnvFile not found." -ForegroundColor Red
    exit 1
}

# Run migrations
$AlembicBin = Join-Path $BaseDir 'venv/Scripts/alembic.exe'
if (Test-Path $AlembicBin) {
    & $AlembicBin -c api/alembic.ini upgrade head
} else {
    alembic -c api/alembic.ini upgrade head
}

