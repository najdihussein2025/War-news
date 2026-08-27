param(
    [Parameter(Mandatory=$true)]
    [string]$PostFile
)

$instruction = Get-Content -Path ".\instruction.txt" -Raw -Encoding UTF8
$newsText    = Get-Content -Path $PostFile -Raw -Encoding UTF8

$fullPrompt = $instruction + " " + $newsText

$headers = @{
    "Authorization" = "Bearer 8621398169a544929ec042986c11ce71"
    "Content-Type"  = "application/json"
}

$body = @{
    model    = "gpt-oss:20b"
    messages = @(@{ role = "user"; content = $fullPrompt })
    stream   = $false
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Uri "http://192.168.40.25:11435/ollama/api/chat" -Method Post -Headers $headers -Body $body
$response.message.content