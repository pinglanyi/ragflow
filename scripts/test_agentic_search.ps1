[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ApiKey,
    [Parameter(Mandatory = $true)][string]$Query,
    [string]$BaseUrl = "http://127.0.0.1:9380",
    [string]$ChatId = "1c9dc6468a2511f1b194b520b0860b27",
    [string[]]$DatasetIds = @("982c06185fc011f1a9d2a33ecabf0a06"),
    [string]$Model = "deepseek-v4-flash@parser@Tongyi-Qianwen",
    [ValidateRange(1, 4)][int]$Reasoning = 3,
    [int]$TopN = 8,
    [double]$SimilarityThreshold = 0.2,
    [int]$TimeoutSec = 300,
    [string]$SessionId = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"
$BaseUrl = $BaseUrl.TrimEnd('/')
if (-not $LogPath) {
    $LogPath = Join-Path (Join-Path $PSScriptRoot "..\logs") ("agentic-search-{0}.jsonl" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
}
New-Item -ItemType Directory -Path (Split-Path -Parent $LogPath) -Force | Out-Null

function Protect-LogValue {
    param([object]$Value)
    if ($null -eq $Value) { return $null }
    $json = $Value | ConvertTo-Json -Depth 60 -Compress
    $json = $json -replace [regex]::Escape($ApiKey), "<REDACTED_API_KEY>"
    try { return $json | ConvertFrom-Json } catch { return $json }
}

function Write-Event {
    param([string]$Event, [hashtable]$Fields)
    $record = [ordered]@{ timestamp = (Get-Date).ToUniversalTime().ToString("o"); event = $Event }
    foreach ($name in $Fields.Keys) { $record[$name] = Protect-LogValue $Fields[$name] }
    ($record | ConvertTo-Json -Depth 60 -Compress) | Add-Content -LiteralPath $LogPath -Encoding UTF8
}

$uri = "$BaseUrl/api/v1/agentic-search"
$body = @{
    query = $Query
    chat_id = $ChatId
    dataset_ids = @($DatasetIds)
    model = $Model
    reasoning = $Reasoning
    top_n = $TopN
    similarity_threshold = $SimilarityThreshold
}
if ($SessionId) { $body.session_id = $SessionId }

$headers = @{ Authorization = "Bearer $ApiKey"; "Content-Type" = "application/json" }
$started = Get-Date
Write-Host "[$($started.ToString('HH:mm:ss'))] -> POST agentic_search"
Write-Event "request" @{ method = "POST"; uri = $uri; authorization = "Bearer <REDACTED_API_KEY>"; body = $body }

try {
    $response = Invoke-RestMethod -Uri $uri -Headers $headers -Method Post -Body ($body | ConvertTo-Json -Depth 20) -TimeoutSec $TimeoutSec
    $elapsed = [math]::Round(((Get-Date) - $started).TotalMilliseconds)
    $succeeded = ($null -ne $response.code -and [int]$response.code -eq 0)
    Write-Event "response" @{ success = $succeeded; elapsed_ms = $elapsed; response = $response }
    if (-not $succeeded) {
        Write-Error ("Agentic Search failed: {0}" -f ($response | ConvertTo-Json -Depth 20 -Compress))
        exit 1
    }
    Write-Host "[$((Get-Date).ToString('HH:mm:ss'))] <- success (${elapsed}ms)"
    Write-Host ""
    Write-Host "===== Agentic Search result =====" -ForegroundColor Cyan
    Write-Host $response.data.answer
    Write-Host ""
    Write-Host ("request_id={0} session_id={1} references={2}" -f $response.data.request_id, $response.data.session_id, $response.data.reference_count)
    foreach ($reference in ($response.data.references | Select-Object -First 10)) {
        Write-Host ("- {0} | similarity={1} | chunk={2}" -f $reference.document_name, $reference.similarity, $reference.chunk_id)
    }
} catch {
    $elapsed = [math]::Round(((Get-Date) - $started).TotalMilliseconds)
    $message = $_.Exception.Message
    $responseBody = $_.ErrorDetails.Message
    Write-Event "response" @{ success = $false; elapsed_ms = $elapsed; error = $message; response = $responseBody }
    throw
}

Write-Host "Log: $((Resolve-Path $LogPath).Path)" -ForegroundColor Green
