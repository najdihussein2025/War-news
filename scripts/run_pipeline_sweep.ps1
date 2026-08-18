# Run a foreground drain in the dedicated pipeline-worker container.
# Do not use `docker compose exec backend` — that process is killed by uvicorn --reload.
param(
    [int]$Limit,
    [switch]$Once
)

Set-Location $PSScriptRoot\..

$cliArgs = @("python", "-m", "app.core.scripts.run_pipeline_sweep_cli")
if ($Once) {
    $cliArgs += "--once"
} else {
    $cliArgs += "--drain"
}
if ($PSBoundParameters.ContainsKey("Limit")) {
    $cliArgs += @("--limit", "$Limit")
}

docker compose exec pipeline-worker @cliArgs

