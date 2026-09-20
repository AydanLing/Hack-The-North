# CuBot 8-hour shape campaign for Windows (PowerShell)
# Run from PowerShell (not Cursor Agent). Machine should stay awake.
#
# Usage (after setup below):
#   cd Hack-The-North\cubot-v2
#   powershell -ExecutionPolicy Bypass -File tools\run_campaign_8h.ps1
#   powershell -ExecutionPolicy Bypass -File tools\run_campaign_8h.ps1 -Hours 8

param(
    [double]$Hours = 8,
    [int]$Workers = 3,
    [double]$TimeBudget = 200,
    [int]$K = 4
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$Out = Join-Path $Root "out\campaign-$Stamp"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Log = Join-Path $Out "campaign.log"

function Log([string]$msg) {
    $line = "[{0}] {1}" -f ((Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")), $msg
    Write-Host $line
    Add-Content -Path $Log -Value $line
}

$Deadline = (Get-Date).AddHours($Hours)
$env:PYTHONPATH = $Root
$Py = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" }
      elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" }
      else { throw "python not found — create .venv first (see CAMPAIGN-WINDOWS.md)" }

Log "campaign start hours=$Hours workers=$Workers budget=${TimeBudget}s out=$Out"
Log "Profile: gentle (holding/ground/overhang/torque hard gates). Only PASS rows are exportable."

function Build-Queue([string]$Mode, [string]$Dest) {
    & $Py tools\build_campaign_queue.py --mode $Mode -o $Dest
    if ($LASTEXITCODE -ne 0) { throw "build_campaign_queue failed: $Mode" }
}

function Run-Batch([string]$Queue, [string]$Dest, [string]$Label) {
    if (-not (Test-Path $Queue) -or (Get-Item $Queue).Length -eq 0) {
        Log "skip empty queue $Label"
        return $true
    }
    if ((Get-Date) -ge $Deadline) {
        Log "stop: deadline before $Label"
        return $false
    }
    $n = (Get-Content $Queue | Measure-Object -Line).Lines
    Log "=== $Label ($n items) ==="
    & $Py -u tools\explore_batch.py `
        --queue $Queue `
        --out $Dest `
        --workers $Workers `
        --time-budget $TimeBudget `
        -k $K `
        --max-candidates 8
    return $true
}

Build-Queue "pick-key" (Join-Path $Out "queue-pick.jsonl")
Build-Queue "places-vehicles" (Join-Path $Out "queue-places-vehicles.jsonl")
Build-Queue "candidates" (Join-Path $Out "queue-all-candidates.jsonl")
Build-Queue "loose-handoff" (Join-Path $Out "queue-loose-handoff.jsonl")

if (-not (Run-Batch (Join-Path $Out "queue-pick.jsonl") (Join-Path $Out "pick-key") "pick-key recover")) { exit 0 }
if (-not (Run-Batch (Join-Path $Out "queue-loose-handoff.jsonl") (Join-Path $Out "loose-handoff") "loose-handoff gentle")) { exit 0 }
if (-not (Run-Batch (Join-Path $Out "queue-places-vehicles.jsonl") (Join-Path $Out "places-vehicles") "places+vehicles")) { exit 0 }
if (-not (Run-Batch (Join-Path $Out "queue-all-candidates.jsonl") (Join-Path $Out "all-candidates") "all candidates")) { exit 0 }

if ((Get-Date) -lt $Deadline) {
    Log "=== retry-violating pick-key ==="
    & $Py -u tools\explore_batch.py --out (Join-Path $Out "pick-key") --retry-violating `
        --only-unpassed-concepts --workers $Workers --time-budget 280 -k $K
}

Log "campaign finished — export ONLY PASS rows from $Out into handoff/ later"
