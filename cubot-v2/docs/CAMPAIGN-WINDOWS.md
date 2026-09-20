# Windows spam-laptop: exact steps (8-hour campaign)

Do this in **Windows PowerShell** (or Windows Terminal).  
**Not** inside a Cursor Agent chat. Leave the hardware Mac free.

---

## 0) One-time installs (if missing)

1. [Git for Windows](https://git-scm.com/download/win)  
2. [Python 3.12+](https://www.python.org/downloads/) — check **“Add python.exe to PATH”**  
3. Optional: plug in power; **Settings → System → Power → Screen and sleep → Sleep = Never** while it runs  

---

## 1) Paste this block once (clone + deps)

Open PowerShell and paste:

```powershell
cd $HOME\Downloads
git clone https://github.com/AydanLing/Hack-The-North.git
cd Hack-The-North
git checkout imessage-linq-bridge
git pull
cd cubot-v2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
```

If `pip install -e .` fails, install whatever `pyproject.toml` / README lists (numpy, etc.), then:

```powershell
pip install numpy scipy matplotlib
```

You need enough deps that this works:

```powershell
python -c "import cubot; print('ok')"
```

---

## Auto-stop after 8h + export + push

If you want it to **kill the fold job at 8 hours**, then export only PASSes into
`handoff/` and `git push`:

```powershell
cd $HOME\Downloads\Hack-The-North
git pull
cd cubot-v2
powershell -ExecutionPolicy Bypass -File .\tools\run_campaign_friend_8h.ps1 -Hours 8
```

Options:

```powershell
# stop + export, but don't push
powershell -ExecutionPolicy Bypass -File .\tools\run_campaign_friend_8h.ps1 -Hours 8 -NoPush

# stop only (no handoff write)
powershell -ExecutionPolicy Bypass -File .\tools\run_campaign_friend_8h.ps1 -Hours 8 -NoExport
```

Notes:

- Push needs GitHub login on that PC (`gh auth login` or a credential helper).
- `out\` stays local (gitignored); only **PASS** paths go into `handoff\` and get pushed.
- If a fold is already running from the old paste, **Ctrl+C** it first, then start this script (resume-safe).

---

## Manual candidates run (no auto-stop)

Still in `Hack-The-North\cubot-v2`, with venv active:

```powershell
cd $HOME\Downloads\Hack-The-North\cubot-v2
.\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File .\tools\run_campaign_8h.ps1 -Hours 8
```

To run detached (close the window later — use a dedicated window you leave open, or):

```powershell
cd $HOME\Downloads\Hack-The-North\cubot-v2
Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File','.\tools\run_campaign_8h.ps1','-Hours','8'
```

Watch log:

```powershell
Get-Content .\out\campaign-*\campaign.log -Tail 20 -Wait
```

(Pick the newest `out\campaign-...` folder if several exist.)

---

## 3) What it does

Gentle profile only — bad torque / floor / overhang paths **fail**, not PASS.  
Phases: friend’s 66 pick-key shapes → loose handoff replan → places/vehicles → all candidates → retry violators.

Resume: run the same `run_campaign_8h.ps1` again; finished items are skipped.

---

## 4) When 8 hours is up

Don’t commit `out\`. On that PC (or copy PASS `record.json` paths), export winners into `handoff\`, commit, push. Then pull on the Mac for demos.

Rough command after you have a summary/manifest (Mac or Windows once you know the out folder):

```powershell
# inspect
python tools\explore_summary.py --root out\campaign-XXXX\pick-key
```

Then use `export_handoff.py` / `patch_handoff_shapes.py` as on the Mac docs.
