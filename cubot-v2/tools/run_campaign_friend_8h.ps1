# Candidates-only campaign: run up to N hours, then export PASSes and git push.
#
# From cubot-v2 in PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\tools\run_campaign_friend_8h.ps1
#   powershell -ExecutionPolicy Bypass -File .\tools\run_campaign_friend_8h.ps1 -Hours 8 -NoPush
#
# Requires: python with cubot-v2 installed, git remote auth for push.

param(
    [double]$Hours = 8,
    [int]$Workers = 3,
    [double]$TimeBudget = 200,
    [int]$K = 4,
    [string]$Profile = "loose",
    [switch]$NoPush,
    [switch]$NoExport
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Fresh out dir so prior gentle attempts do not block loose retries of the same masks.
$Out = Join-Path $Root ("out\campaign-friend-" + $Profile)
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Log = Join-Path $Out "timed-campaign.log"
$Queue = Join-Path $Out "queue.jsonl"

function Log([string]$msg) {
    $line = "[{0}] {1}" -f ((Get-Date).ToUniversalTime().ToString("s")), $msg
    Write-Host $line
    Add-Content -Path $Log -Value $line
}

$env:PYTHONPATH = $Root
$Py = "python"

Log "start hours=$Hours workers=$Workers profile=$Profile out=$Out"

Log "building candidates queue"
& $Py tools\build_campaign_queue.py --mode candidates -o $Queue
if ($LASTEXITCODE -ne 0) { throw "build_campaign_queue failed" }

$argsList = @(
    "-u", "tools\explore_batch.py",
    "--queue", $Queue,
    "--out", $Out,
    "--workers", "$Workers",
    "--time-budget", "$TimeBudget",
    "-k", "$K",
    "--max-candidates", "8",
    "--profile", $Profile
)

Log "launching explore_batch (will stop after $Hours h if still running)"
$proc = Start-Process -FilePath $Py -ArgumentList $argsList `
    -WorkingDirectory $Root -PassThru -NoNewWindow `
    -RedirectStandardOutput (Join-Path $Out "explore-stdout.log") `
    -RedirectStandardError (Join-Path $Out "explore-stderr.log")

$deadline = (Get-Date).AddHours($Hours)
while (-not $proc.HasExited -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 60
    Log ("still running pid=" + $proc.Id + " until " + $deadline.ToString("s"))
}

if (-not $proc.HasExited) {
    Log ("deadline hit - stopping process tree pid=" + $proc.Id)
    & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
    Start-Sleep -Seconds 2
} else {
    Log ("explore_batch exited on its own code=" + $proc.ExitCode)
}

if ($NoExport) {
    Log "NoExport set - skipping handoff export / push"
    exit 0
}

Log "summarizing PASSes -> handoff-manifest.json"
& $Py tools\explore_summary.py --out $Out
if ($LASTEXITCODE -ne 0) { throw "explore_summary failed" }

$Manifest = Join-Path $Out "handoff-manifest.json"
if (-not (Test-Path $Manifest)) {
    Log "no manifest written - nothing to export"
    exit 0
}
$manifestObj = Get-Content $Manifest -Raw | ConvertFrom-Json
$n = @($manifestObj.shapes).Count
Log ("manifest has " + $n + " PASS shape(s)")
if ($n -eq 0) {
    Log "zero PASSes - nothing to commit/push"
    exit 0
}

Log "exporting PASSes into handoff/ (--no-demo)"
& $Py tools\export_handoff.py --manifest $Manifest --no-demo
if ($LASTEXITCODE -ne 0) { throw "export_handoff failed" }

if ($NoPush) {
    Log "NoPush set - handoff updated locally only"
    exit 0
}

Log "git commit + push handoff"
$Repo = Split-Path -Parent $Root
Set-Location $Repo

git fetch origin
git pull --rebase origin imessage-linq-bridge 2>$null
git add cubot-v2/handoff
$status = git status --porcelain cubot-v2/handoff
if (-not $status) {
    Log "handoff unchanged after export - nothing to push"
    exit 0
}

$msg = "Add campaign PASSes from Windows candidates run ($n shapes)."
git commit -m $msg
if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

git push -u origin HEAD
if ($LASTEXITCODE -ne 0) {
    Log "git push failed - commit is local; fix auth and run: git push -u origin HEAD"
    exit 1
}

Log "done - pushed handoff PASSes"
