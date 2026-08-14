# Keep this file ASCII-only. PowerShell 5.1 can misread UTF-8 .ps1 files
# without a BOM. Put all non-ASCII sample and prompt content in .txt/.json
# files and load it with explicit UTF-8 handling.

$ErrorActionPreference = "Stop"
[System.Net.ServicePointManager]::Expect100Continue = $false

$ScriptDir = $PSScriptRoot
$EnvPath = Join-Path $PSScriptRoot "..\..\.env"
$InstructionPath = Join-Path $ScriptDir "extraction_instruction.txt"
$SamplesDir = Join-Path $ScriptDir "sample_texts"
$ResultsPath = Join-Path $ScriptDir "extraction_results.json"

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

function Get-SampleId {
    param([Parameter(Mandatory = $true)][string]$Name)

    if ($Name -match "sample_(\d+)\.txt$") {
        return [int]$Matches[1]
    }
    return $Name
}

function Save-Results {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.ArrayList]$Items,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $Items | ConvertTo-Json -Depth 100 | Set-Content -Path $Path -Encoding UTF8
}

function ConvertFrom-ModelJson {
    param([AllowNull()][string]$Text)

    if (-not $Text) {
        return $null
    }

    $candidate = $Text.Trim()
    if ($candidate -match "(?s)^```(?:json)?\s*(.*?)\s*```$") {
        $candidate = $Matches[1].Trim()
    }

    try {
        return $candidate | ConvertFrom-Json
    } catch {
        $firstObject = $candidate.IndexOf("{")
        $lastObject = $candidate.LastIndexOf("}")
        if ($firstObject -ge 0 -and $lastObject -gt $firstObject) {
            try {
                return $candidate.Substring($firstObject, $lastObject - $firstObject + 1) | ConvertFrom-Json
            } catch {
                return $null
            }
        }
    }

    return $null
}

$resolvedEnvPath = (Resolve-Path -Path $EnvPath -ErrorAction SilentlyContinue).Path
if (-not $resolvedEnvPath) {
    throw "Missing .env file at $EnvPath"
}
if (-not (Test-Path $InstructionPath)) {
    throw "Missing instruction file at $InstructionPath"
}
if (-not (Test-Path $SamplesDir)) {
    throw "Missing samples directory at $SamplesDir"
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
Write-Host ""

$endpoint = Join-Url -BaseUrl $baseUrl -Path "/api/chat"
$instruction = Get-Content -Path $InstructionPath -Encoding UTF8 -Raw
$samples = @(Get-ChildItem -Path $SamplesDir -Filter "*.txt" | Sort-Object @{ Expression = { Get-SampleId -Name $_.Name } })
$results = New-Object System.Collections.ArrayList
$headers = @{}
if ($apiKey -and $apiKey -ne "your-bearer-token-here") {
    $headers["Authorization"] = "Bearer $apiKey"
}

for ($i = 0; $i -lt $samples.Count; $i++) {
    $sample = $samples[$i]
    $sampleId = Get-SampleId -Name $sample.Name
    Write-Host "Processing sample $($i + 1) of $($samples.Count): $($sample.Name)"

    $postText = Get-Content -Path $sample.FullName -Encoding UTF8 -Raw
    $rawOutput = $null
    $parsedOutput = $null
    $errorText = $null
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

    try {
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
        } | ConvertTo-Json -Depth 12

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
        $parsedOutput = ConvertFrom-ModelJson -Text $rawOutput
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
        Write-Host "ERROR sample ${sampleId}: $errorText"
    } finally {
        $stopwatch.Stop()
    }

    [void]$results.Add([ordered]@{
        sample_id = $sampleId
        khabar_text = $postText
        model_response_raw = $rawOutput
        parsed_json_or_null = $parsedOutput
        error = $errorText
    })
    Save-Results -Items $results -Path $ResultsPath

    $elapsedSeconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 1)
    if ($errorText) {
        Write-Host "Sample $($i + 1) of $($samples.Count) ($($sample.Name)) FAILED after ${elapsedSeconds}s - $errorText"
    } else {
        $isValidJson = $null -ne $parsedOutput
        Write-Host "Sample $($i + 1) of $($samples.Count) ($($sample.Name)) DONE in ${elapsedSeconds}s - valid JSON: $isValidJson"
    }
}

Save-Results -Items $results -Path $ResultsPath
Write-Host "Results written to $ResultsPath"
