# Keep this file ASCII-only. PowerShell 5.1 can misread UTF-8 .ps1 files
# without a BOM, which breaks Arabic text. Put all Arabic content in .txt
# files and load it with Get-Content -Encoding UTF8.

$ErrorActionPreference = "Stop"
[System.Net.ServicePointManager]::Expect100Continue = $false

$ScriptDir = $PSScriptRoot
$EnvPath = Join-Path $PSScriptRoot "..\..\.env"
$InstructionPath = Join-Path $ScriptDir "instruction.txt"
$SamplesDir = Join-Path $ScriptDir "samples"
$ResultsPath = Join-Path $ScriptDir "results.txt"

function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Key,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        throw "Missing .env file at $Path"
    }

    $escapedKey = [regex]::Escape($Key)
    $pattern = "^\s*$escapedKey\s*=\s*(.*)\s*$"
    foreach ($line in Get-Content -Path $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }

        if ($line -match $pattern) {
            $value = $Matches[1].Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }

    throw "Missing required environment value '$Key' in $Path"
}

function Join-Url {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseUrl,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return $BaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/")
}

$resolvedEnvPath = (Resolve-Path -Path $EnvPath -ErrorAction SilentlyContinue).Path
if (-not $resolvedEnvPath) {
    throw "Missing .env file at $EnvPath"
}

$baseUrl = Get-EnvValue -Key "OLLAMA_BASE_URL" -Path $resolvedEnvPath
$apiKey = Get-EnvValue -Key "OLLAMA_API_KEY" -Path $resolvedEnvPath
$model = Get-EnvValue -Key "OLLAMA_MODEL" -Path $resolvedEnvPath
$timeoutValue = Get-EnvValue -Key "OLLAMA_TIMEOUT_SECONDS" -Path $resolvedEnvPath

if (-not $baseUrl) {
    throw "OLLAMA_BASE_URL is empty in $resolvedEnvPath"
}
if (-not $apiKey) {
    throw "OLLAMA_API_KEY is empty in $resolvedEnvPath"
}
if (-not $model) {
    throw "OLLAMA_MODEL is empty in $resolvedEnvPath"
}

$timeoutSeconds = 60
if ($timeoutValue) {
    $timeoutSeconds = [int]$timeoutValue
}

Write-Host "Pre-flight configuration"
Write-Host "ENV file found: $(Test-Path $resolvedEnvPath)"
Write-Host "ENV path: $resolvedEnvPath"
Write-Host "OLLAMA_BASE_URL: $baseUrl"
Write-Host "OLLAMA_MODEL: $model"
Write-Host "OLLAMA_API_KEY: loaded (length: $($apiKey.Length))"
Write-Host ""

$endpoint = Join-Url -BaseUrl $baseUrl -Path "/api/chat"
$instruction = Get-Content -Path $InstructionPath -Encoding UTF8 -Raw
$samples = Get-ChildItem -Path $SamplesDir -Filter "*.txt" | Sort-Object Name

Set-Content -Path $ResultsPath -Value "" -Encoding UTF8

foreach ($sample in $samples) {
    $header = "=== $($sample.Name) ==="
    Write-Host $header
    Add-Content -Path $ResultsPath -Value $header -Encoding UTF8

    try {
        $postText = Get-Content -Path $sample.FullName -Encoding UTF8 -Raw
        $prompt = $instruction + "`n" + $postText
        $body = @{
            model = $model
            stream = $false
            messages = @(
                @{
                    role = "user"
                    content = $prompt
                }
            )
        } | ConvertTo-Json -Depth 8
        $headers = @{}
        if ($apiKey -and $apiKey -ne "your-bearer-token-here") {
            $headers["Authorization"] = "Bearer $apiKey"
        }
        if ($headers.ContainsKey("Content-Type")) {
            $headers.Remove("Content-Type")
        }

        $response = Invoke-RestMethod `
            -Method Post `
            -Uri $endpoint `
            -Headers $headers `
            -ContentType "application/json; charset=utf-8" `
            -Body $body `
            -TimeoutSec $timeoutSeconds

        $output = $null
        if ($response.message -and $response.message.content) {
            $output = $response.message.content
        } elseif ($response.response) {
            $output = $response.response
        } else {
            $output = $response | ConvertTo-Json -Depth 8
        }

        Write-Host $output
        Add-Content -Path $ResultsPath -Value $output -Encoding UTF8
    } catch {
        $serverBody = $_.ErrorDetails.Message
        if (-not $serverBody -and $_.Exception.Response) {
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                if ($stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    try {
                        $serverBody = $reader.ReadToEnd()
                    } finally {
                        $reader.Dispose()
                    }
                }
            } catch {
                $serverBody = $null
            }
        }

        if ($serverBody) {
            $errorText = "ERROR: $($_.Exception.Message)`n$serverBody"
        } else {
            $errorText = "ERROR: $($_.Exception.Message)"
        }
        Write-Host $errorText
        Add-Content -Path $ResultsPath -Value $errorText -Encoding UTF8
    }

    Write-Host ""
    Add-Content -Path $ResultsPath -Value "" -Encoding UTF8
}

Write-Host "Results written to $ResultsPath"
