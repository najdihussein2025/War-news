# Thin wrapper: every docker compose call for the DEV stack goes through here so the
# project name, compose file, env file and project directory are always explicit.
#   .\scripts\dev.ps1 up -d --build
#   .\scripts\dev.ps1 exec backend pytest tests -q
#   .\scripts\dev.ps1 ps
# The repo root is derived from this script's own location (no drive letter, no cwd).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env.dev"
$ComposeFile = Join-Path $Root "docker-compose.dev.yml"

if (-not (Test-Path $EnvFile)) { throw ".env.dev not found at $EnvFile (copy .env.example and set the dev values)." }
if ($args -contains "-p" -or $args -contains "--project-name" -or $args -contains "-f" -or $args -contains "--file") {
    throw "dev.ps1 fixes the project (war-news-dev) and compose file; do not pass -p/-f."
}

docker compose -p war-news-dev --project-directory $Root -f $ComposeFile --env-file $EnvFile @args
exit $LASTEXITCODE
