# hardware

Scripts that talk to the real CuBot chain: 27 Feetech STS3215 servos, 4:1 gearing, one per hinge, on one serial bus.

## zero_servos.py

Zeroes the servos **one at a time**, with multi-turn handling.

```bash
pip install feetech-servo-sdk                      # provides the scservo_sdk module

python hardware/zero_servos.py --port COM5 --scan   # report every servo, move nothing
python hardware/zero_servos.py --port COM5          # dry run: prints every register write it would make
python hardware/zero_servos.py --port COM5 --execute --enable-multiturn   # configure, then drive each hinge to 0
python hardware/zero_servos.py --port COM5 --execute --mode set-home      # current pose becomes the new zero
```

| flag | what it does |
|---|---|
| `--scan` | pings IDs 1–27 and prints position, turns, offset, mode, angle limits, multi-turn yes/no, volts, temperature |
| `--execute` | actually writes; without it nothing is sent |
| `--mode goto` | (default) drive the hinge to 0°, unwinding in steps of ≤ `--step-deg` (90° default) |
| `--mode set-home` | leave the hinge where it is and write the offset register so it reads 0 |
| `--enable-multiturn` | write multi-turn config to EEPROM first (mode 0, both angle limits 0), then read it back |
| `--check-multiturn` | refuse to move any servo that is not in multi-turn |
| `--yes` | skip the per-servo confirmation |
| `--ids 5 6 7` | only these servo IDs |

Safety: one servo at a time, torque capped at 40 %, slow speed and acceleration, per-servo confirmation, and Ctrl-C
disables torque on every servo. Torque is released after each hinge reaches zero.

### Multi-turn

Without multi-turn, position wraps every 4096 ticks, so with 4:1 gearing a hinge at 90° and one at 90° plus a full
turn read the same and "zero" is ambiguous. With multi-turn the servo counts turns, but the position still travels the
bus as two bytes with bit 15 as the sign, so the usable range is ±32767 ticks = ±8 motor turns = **±2 hinge turns**.
The script warns past 80 % of that and refuses to drive a hinge whose reading has already aliased (unwind it by hand).

Normal folding only uses −120…+120° of hinge rotation (±1.33 motor turns), so this only matters after a wind-up.

### Verify before the first `--execute`

These came from the published SMS/STS memory table, not from your servos. Confirm with the Feetech debug software:

1. **Register addresses** (top of the script): lock 55, angle limits 9/11, offset 31, mode 33, torque enable 40,
   goal acc/pos/speed 41/42/46, torque limit 48, present pos/load/volt/temp 56/60/62/63, moving 66.
2. **How multi-turn is enabled.** The script uses mode 0 with both angle limits set to 0. Some firmware instead uses
   the "step servo" mode (mode 3). `--scan` prints mode and limits, so compare against a servo you have configured
   by hand in the Feetech software.
3. **How the offset register behaves** in `set-home`: the script writes `offset - present` and then checks that the
   servo reads ~0. If your firmware applies the offset the other way, that check fails loudly rather than silently
   leaving a wrong zero.
4. **Gearing and direction:** `GEAR_RATIO = 4.0` from `cubot-v2/config/machine.toml`. Check the sign convention too:
   the script assumes a positive tick count is a positive hinge angle.

### Testing status

Written against the emulated bus in this session (27 servos, some wound 1–2 turns, one not in multi-turn, one
unplugged): scan, dry run, `goto` unwinding, `set-home`, `--enable-multiturn`, the range check and the
non-responding-servo path all behave correctly. **It has not run against real hardware.**
