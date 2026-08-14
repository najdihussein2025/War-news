# Keep this file ASCII-only. PowerShell 5.1 can misread UTF-8 .ps1 files
# without a BOM. Put all non-ASCII sample and prompt content in .txt files
# and load it with explicit UTF-8 handling.

param(
    [Parameter(Mandatory = $true)]
    [string]$SampleFile
)

$ErrorActionPreference = "Stop"
[System.Net.ServicePointManager]::Expect100Continue = $false

$ScriptDir = $PSScriptRoot
$EnvPath = Join-Path $PSScriptRoot "..\..\.env"
$InstructionPath = Join-Path $ScriptDir "extraction_instruction.txt"
$SamplesDir = Join-Path $ScriptDir "sample_texts"

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

function Test-JsonValidity {
    param([AllowNull()][string]$Text)

    if (-not $Text) {
        return $false
    }

    try {
        $null = $Text.Trim() | ConvertFrom-Json
        return $true
    } catch {
        return $false
    }
}

$resolvedEnvPath = (Resolve-Path -Path $EnvPath -ErrorAction SilentlyContinue).Path
if (-not $resolvedEnvPath) {
    throw "Missing .env file at $EnvPath"
}
if (-not (Test-Path $InstructionPath)) {
    throw "Missing instruction file at $InstructionPath"
}

$samplePath = Join-Path $SamplesDir $SampleFile
$resolvedSamplePath = (Resolve-Path -Path $samplePath -ErrorAction SilentlyContinue).Path
if (-not $resolvedSamplePath) {
    throw "Missing sample file at $samplePath"
}

$baseUrl = Get-EnvValue -Key "OLLAMA_BASE_URL" -Path $resolvedEnvPath
$apiKey = Get-EnvValue -Key "OLLAMA_API_KEY" -Path $resolvedEnvPath
$model = Get-EnvValue -Key "EXTRACTION_OLLAMA_MODEL" -Path $resolvedEnvPath
$timeoutValue = Get-EnvValue -Key "OLLAMA_TIMEOUT_SECONDS" -Path $resolvedEnvPath

if (-not $baseUrl) {
    throw "OLLAMA_BASE_URL is empty in $resolvedEnvPath"
}
if (-not $apiKey) {
    throw "OLLAMA_API_KEY is empty in $resolvedEnvPath"
}
if (-not $model) {
    throw "EXTRACTION_OLLAMA_MODEL is empty in $resolvedEnvPath"
}

$timeoutSeconds = 60
if ($timeoutValue) {
    $timeoutSeconds = [int]$timeoutValue
}

Write-Host "Pre-flight configuration"
Write-Host "ENV file found: $(Test-Path $resolvedEnvPath)"
Write-Host "ENV path: $resolvedEnvPath"
Write-Host "OLLAMA_BASE_URL: $baseUrl"
Write-Host "EXTRACTION_OLLAMA_MODEL: $model"
Write-Host "OLLAMA_API_KEY: loaded (length: $($apiKey.Length))"
Write-Host "OLLAMA_TIMEOUT_SECONDS: $timeoutSeconds"
Write-Host "SampleFile: $SampleFile"
Write-Host ""

$instruction = Get-Content -Path $InstructionPath -Encoding UTF8 -Raw
$postText = Get-Content -Path $resolvedSamplePath -Encoding UTF8 -Raw
$prompt = $instruction + "`n" + $postText
$endpoint = Join-Url -BaseUrl $baseUrl -Path "/api/chat"
$headers = @{}
if ($apiKey -and $apiKey -ne "your-bearer-token-here") {
    $headers["Authorization"] = "Bearer $apiKey"
}

$body = @{
    model = $model
    stream = $false
    messages = @(
        @{
            role = "user"
            content = $prompt
        }
    )
} | ConvertTo-Json -Depth 12

Write-Host "DEBUG - URI: $endpoint"
$debugHeaders = @{}
foreach ($key in $headers.Keys) {
    $value = [string]$headers[$key]
    if ($key -eq "Authorization" -and $value.Length -gt 16) {
        $debugHeaders[$key] = $value.Substring(0, 13) + "...length=" + $value.Length
    } else {
        $debugHeaders[$key] = $value
    }
}
Write-Host "DEBUG - Headers: $($debugHeaders | ConvertTo-Json -Compress)"

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$rawOutput = $null
$errorText = $null
try {
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri $endpoint `
        -Headers $headers `
        -ContentType "application/json; charset=utf-8" `
        -Body $body `
        -TimeoutSec $timeoutSeconds

    if ($response.message -and $response.message.content) {
        $rawOutput = $response.message.content
    } elseif ($response.response) {
        $rawOutput = $response.response
    } else {
        $rawOutput = $response | ConvertTo-Json -Depth 12
    }
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
        $errorText = "$($_.Exception.Message)`n$serverBody"
    } else {
        $errorText = $_.Exception.Message
    }
} finally {
    $stopwatch.Stop()
}

$isValidJson = Test-JsonValidity -Text $rawOutput

Write-Host "ElapsedSeconds: $([math]::Round($stopwatch.Elapsed.TotalSeconds, 3))"
Write-Host "ValidJson: $isValidJson"
if ($errorText) {
    Write-Host "Error:"
    Write-Host $errorText
}
Write-Host "Response:"
Write-Host $rawOutput
