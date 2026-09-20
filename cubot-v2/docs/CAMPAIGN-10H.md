# Campaign: generate + hard-validate every path (other machine)

Default wall clock: **8 hours** (`./tools/run_campaign_10h.sh` or `… 8`).

## Split of labor

| Machine | Job |
|---------|-----|
| **Hardware / demo laptop** | Leave free for bridge, MuJoCo, USB. Do **not** run the campaign here. |
| **Spam box** | Only place that generates/optimizes for hours. |

## How to run on the other computer (important)

**Do not** drive the 8-hour job from a Cursor Agent chat or a Cloud Agent session.

| Approach | Verdict |
|----------|---------|
| **Terminal + `nohup` or `tmux`/`screen`** | **Yes — do this.** Survives closing the laptop lid (if set to not sleep), closing Cursor, network blips. |
| Cursor Agent on the same account (second machine) | Risky. Agents can be interrupted, rate-limited, or stop when the chat ends; two agents also fight over the same git tree if both commit. |
| Cloud Agent / cloud VM coding session | Same problem for a multi-hour fold queue unless you only use it to *start* a detached `nohup` and then leave it alone. Prefer a real shell on a machine that stays awake. |

Same Cursor account on two machines is fine for **editing**. For **this campaign**, open a normal terminal on the spam box and run the script outside the agent.

## What “valid path” means (gentle)

Every accepted move must clear `config/profiles/gentle.toml` (holding ≤6 N·m, stall ≤10.6, ground ≤15 mm, pivot dip ≤25 mm, overhang/balance, CAD, tether). Only **PASS** (`complete` + `hard_ok` + `goal_is_mask`) should go to `handoff/`.

## Spam box — setup once

```bash
git clone <repo-url> Hack-The-North
cd Hack-The-North
git pull
cd cubot-v2
uv sync   # or your venv with project deps
chmod +x tools/run_campaign_10h.sh
# Optional: stop the machine from sleeping for 8h (macOS: caffeinate)
```

## Spam box — start 8 hours (detached)

```bash
cd Hack-The-North/cubot-v2

# macOS: keep awake while campaign runs
caffeinate -dimsu nohup ./tools/run_campaign_10h.sh 8 > /tmp/cubot-campaign.log 2>&1 &

# Linux:
# nohup ./tools/run_campaign_10h.sh 8 > /tmp/cubot-campaign.log 2>&1 &

echo $!   # save PID
tail -f /tmp/cubot-campaign.log
```

Or inside `tmux` / `screen` so you can disconnect SSH safely.

Knobs: `CAMPAIGN_WORKERS=3` (≤3 on 8-core), `CAMPAIGN_TIME_BUDGET=200`, `CAMPAIGN_K=4`.

Resume-safe: re-run the same command; finished `(name, variant)` rows are skipped.

## Afterward

```bash
python tools/explore_summary.py --root out/campaign-XXXX/pick-key
# export ONLY PASSes → handoff/, commit, push
```

Pull on the hardware laptop for demos.
