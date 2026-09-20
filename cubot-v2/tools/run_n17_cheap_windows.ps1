# 17-cube cheap-fold campaign for the spare Windows laptop.
#
# Mac is already chewing k1–k4 of out/n17-cheap. This box takes the leftover
# 5-fold footprints (k5-*.txt) so the two machines do not duplicate work.
#
#   cd Hack-The-North\cubot-v2
#   powershell -ExecutionPolicy Bypass -File .\tools\run_n17_cheap_windows.ps1
#   powershell -ExecutionPolicy Bypass -File .\tools\run_n17_cheap_windows.ps1 -Hours 6 -Workers 8
#
# Results land in out\n17-cheap-win (gitignored). Copy that folder back to the
# Mac, or pass -Push if this PC can `git push` to origin/main.

param(
    [double]$Hours = 8,
    [int]$Workers = 8,
    [double]$TimeBudget = 60,
    [int]$K = 3,
    [string]$Profile = "loose",
    [switch]$Push
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Out = Join-Path $Root "out\n17-cheap-win"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$Log = Join-Path $Out "campaign.log"
$Queue = Join-Path $Out "queue.jsonl"
$Masks = Join-Path $Root "data\candidates\n17-cheap"

function Log([string]$msg) {
    $line = "[{0}] {1}" -f ((Get-Date).ToUniversalTime().ToString("s")), $msg
    Write-Host $line
    Add-Content -Path $Log -Value $line
}

$env:PYTHONPATH = $Root
$Py = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" }
      elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" }
      else { throw "python not found — create .venv first (pip install -e .)" }

if (-not (Test-Path $Masks)) {
    throw "missing $Masks — git pull on main so data/candidates/n17-cheap is present"
}

Log "building k5-only queue (Mac owns k1-k4)"
& $Py -c @"
import json
from pathlib import Path
root = Path(r'$Masks')
out = Path(r'$Queue')
n = 0
with out.open('w', encoding='utf-8') as f:
    for p in sorted(root.glob('k5-*.txt')):
        f.write(json.dumps({
            'name': p.stem,
            'mask': str(Path('data/candidates/n17-cheap') / p.name).replace('\\', '/'),
            'category': 'n17-forward',
        }) + '\n')
        n += 1
print(n)
"@
if ($LASTEXITCODE -ne 0) { throw "queue build failed" }
$n = (Get-Content $Queue | Measure-Object -Line).Lines
Log "queue has $n k5 masks, workers=$Workers, $Hours h cap, out=$Out"

$argsList = @(
    "-u", "tools\explore_batch.py",
    "--queue", $Queue,
    "--out", $Out,
    "--machine", "config\machine-17.toml",
    "--profile", $Profile,
    "--workers", "$Workers",
    "--time-budget", "$TimeBudget",
    "-k", "$K",
    "--max-candidates", "6"
)

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
    Log ("deadline - stopping pid=" + $proc.Id)
    & taskkill.exe /PID $proc.Id /T /F 2>$null | Out-Null
    Start-Sleep -Seconds 2
} else {
    Log ("explore_batch exited code=" + $proc.ExitCode)
}

$harvest = @("tools\harvest_and_push.py", "--campaign", $Out)
if ($Push) { $harvest += "--push" }
Log "harvesting PASSes into handoff-17"
& $Py @harvest
if ($LASTEXITCODE -ne 0) { throw "harvest_and_push failed" }
Log "done"
