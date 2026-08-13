# Keep this file ASCII-only. Put sample content in .txt files.

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path -Path (Join-Path $PSScriptRoot "..\..")
$ScriptPath = Join-Path $PSScriptRoot "run_live_relevance_check.py"

Push-Location $ProjectRoot
try {
    python $ScriptPath @args
} finally {
    Pop-Location
}
