#!/usr/bin/env python3
"""zero_servos.py — zero the 27 CuBot hinge servos (Feetech STS3215, multi-turn), one at a time.

    python hardware/zero_servos.py --port COM5 --scan             # find and report every servo, move nothing
    python hardware/zero_servos.py --port COM5                    # dry run: print exactly what would be written
    python hardware/zero_servos.py --port COM5 --execute          # drive each servo to zero, one at a time
    python hardware/zero_servos.py --port COM5 --execute --mode set-home   # make the CURRENT pose the new zero
    python hardware/zero_servos.py --port COM5 --execute --ids 5 6 7       # only these servo IDs

Two meanings of "zero", pick with --mode:
  goto      (default) drive the servo to position 0, i.e. the straight chain. Multi-turn safe: if a joint has wound
            up several turns, it unwinds in steps of at most --step-deg of hinge rotation instead of one big command.
  set-home  leave the hinge where it is and redefine that position as 0 by writing the servo's position-offset
            register. Use after mechanical assembly, with every module held straight.

Multi-turn: STS3215 servos count turns only when multi-turn is enabled, otherwise position wraps every 4096 ticks and
a hinge past one turn reads the same as one near zero. With GEAR_RATIO = 4, one hinge turn is 4 motor turns, so this
matters for us. --enable-multiturn writes that configuration (EEPROM) before zeroing; --check-multiturn only reports.

SAFETY
  * Nothing moves without --execute. Every move is one servo at a time and each one is confirmed unless --yes.
  * Speed, acceleration and torque are capped by the constants below; Ctrl-C disables torque on every servo.
  * Run with the chain supported and clear of obstacles: a servo that has wound up will take the long way back.

REGISTERS: the addresses below are the published SMS/STS memory table, but firmware revisions differ. Check them
against your servos with the Feetech debug software before the first --execute run; --scan prints what it reads.
"""
from __future__ import annotations

import argparse
import sys
import time

# ----------------------------------------------------------------------------- machine constants
BAUD = 1_000_000          # STS3215 factory default
IDS = list(range(1, 28))  # servo 1..27, one per hinge (module 27's hinge is unused but still wired)
GEAR_RATIO = 4.0          # motor turns per hinge turn (machine.toml: "STS3215 x 4:1")
TICKS_PER_TURN = 4096     # motor ticks per motor turn
HINGE_TRAVEL_DEG = 120.0  # detents at -120 / 0 / +120 deg of hinge rotation

# Multi-turn range: positions travel the bus as 2 bytes with bit 15 as the sign, so |position| <= 32767 ticks.
# That is +-8 motor turns, i.e. +-2 hinge turns at 4:1. Past it the reading aliases and zeroing is not trustworthy.
MULTITURN_TICK_LIMIT = 32767
RANGE_WARN_FRACTION = 0.8

# Motion limits used by this script (conservative; the fold controller may use more).
MOVE_SPEED = 300          # ticks/s in the servo's own units
MOVE_ACC = 20             # servo acceleration units
TORQUE_LIMIT_PERCENT = 40 # % of max torque while zeroing
STEP_DEG_DEFAULT = 90.0   # max hinge degrees per single goal-position command
MOVE_TIMEOUT_S = 8.0
POS_TOLERANCE_TICKS = 20

# ----------------------------------------------------------------------------- SMS/STS register map (verify!)
EEPROM_LOCK = 55          # 0 = EEPROM writable, 1 = locked
MIN_ANGLE_LIMIT = 9       # 2 bytes; both limits 0 => multi-turn (no single-turn clamp)
MAX_ANGLE_LIMIT = 11      # 2 bytes
POSITION_OFFSET = 31      # 2 bytes, signed; added to the raw encoder reading
MODE = 33                 # 0 = position servo, 1 = wheel/speed, 2 = PWM, 3 = step
TORQUE_ENABLE = 40        # 0 = off, 1 = on
GOAL_ACC = 41             # 1 byte
GOAL_POSITION = 42        # 2 bytes, signed in multi-turn
GOAL_SPEED = 46           # 2 bytes
TORQUE_LIMIT = 48         # 2 bytes, 0..1000 = 0..100 %
PRESENT_POSITION = 56     # 2 bytes, signed in multi-turn
PRESENT_SPEED = 58        # 2 bytes
PRESENT_LOAD = 60         # 2 bytes
PRESENT_VOLTAGE = 62      # 1 byte, 0.1 V
PRESENT_TEMPERATURE = 63  # 1 byte, deg C
MOVING = 66               # 1 byte


def ticks_to_hinge_deg(ticks: int) -> float:
  return ticks / TICKS_PER_TURN * 360.0 / GEAR_RATIO


def hinge_deg_to_ticks(deg: float) -> int:
  return int(round(deg * GEAR_RATIO / 360.0 * TICKS_PER_TURN))


class Bus:
  """Thin wrapper over the Feetech SDK: byte-level register access with retries."""

  def __init__(self, port: str, baud: int = BAUD, dry_run: bool = True):
    try:
      from scservo_sdk import PortHandler, sms_sts  # feetech-servo-sdk
    except ImportError as exc:  # pragma: no cover - depends on the machine
      raise SystemExit("Feetech SDK not found. Install it with:  pip install feetech-servo-sdk\n"
                       "(it provides the 'scservo_sdk' module used here)") from exc
    self.dry_run = dry_run
    self.port = PortHandler(port)
    if not self.port.openPort():
      raise SystemExit(f"could not open {port}")
    if not self.port.setBaudRate(baud):
      raise SystemExit(f"could not set baud {baud} on {port}")
    self.packet = sms_sts(self.port)

  def close(self):
    self.port.closePort()

  # ---- reads
  def _check(self, sid: int, what: str, result, err):
    if result != 0 or err != 0:
      raise IOError(f"servo {sid}: {what} failed (comm {result}, servo error {err})")

  def read1(self, sid: int, addr: int) -> int:
    for attempt in range(3):
      value, result, err = self.packet.read1ByteTxRx(sid, addr)
      if result == 0 and err == 0:
        return value
      time.sleep(0.02)
    self._check(sid, f"read1({addr})", result, err)

  def read2(self, sid: int, addr: int, signed: bool = False) -> int:
    for attempt in range(3):
      value, result, err = self.packet.read2ByteTxRx(sid, addr)
      if result == 0 and err == 0:
        # Feetech encodes negatives with bit 15 as the sign, not two's complement.
        return -(value & 0x7FFF) if (signed and value & 0x8000) else value
      time.sleep(0.02)
    self._check(sid, f"read2({addr})", result, err)

  # ---- writes (no-ops in a dry run)
  def write1(self, sid: int, addr: int, value: int, why: str = ""):
    print(f"    write1 servo {sid:2d} reg {addr:3d} = {value}{'  # ' + why if why else ''}")
    if self.dry_run:
      return
    self._check(sid, f"write1({addr})", *self.packet.write1ByteTxRx(sid, addr, value))

  def write2(self, sid: int, addr: int, value: int, why: str = ""):
    raw = (abs(value) | 0x8000) if value < 0 else value
    print(f"    write2 servo {sid:2d} reg {addr:3d} = {value}{'  # ' + why if why else ''}")
    if self.dry_run:
      return
    self._check(sid, f"write2({addr})", *self.packet.write2ByteTxRx(sid, addr, raw))

  def ping(self, sid: int):
    model, result, err = self.packet.ping(sid)
    return None if (result != 0 or err != 0) else model


# ----------------------------------------------------------------------------- multi-turn
def multiturn_state(bus: Bus, sid: int) -> dict:
  return dict(mode=bus.read1(sid, MODE),
              min_limit=bus.read2(sid, MIN_ANGLE_LIMIT),
              max_limit=bus.read2(sid, MAX_ANGLE_LIMIT),
              offset=bus.read2(sid, POSITION_OFFSET, signed=True))


def multiturn_ok(state: dict) -> bool:
  """Multi-turn = position mode with the single-turn clamp removed (both angle limits 0)."""
  return state["mode"] == 0 and state["min_limit"] == 0 and state["max_limit"] == 0


def enable_multiturn(bus: Bus, sid: int):
  """Write the multi-turn configuration to EEPROM, then read it back."""
  bus.write1(sid, TORQUE_ENABLE, 0, "torque off before EEPROM write")
  bus.write1(sid, EEPROM_LOCK, 0, "unlock EEPROM")
  bus.write1(sid, MODE, 0, "position mode")
  bus.write2(sid, MIN_ANGLE_LIMIT, 0, "no single-turn clamp -> multi-turn")
  bus.write2(sid, MAX_ANGLE_LIMIT, 0, "no single-turn clamp -> multi-turn")
  bus.write1(sid, EEPROM_LOCK, 1, "lock EEPROM")
  if bus.dry_run:
    return True
  time.sleep(0.05)
  state = multiturn_state(bus, sid)
  if not multiturn_ok(state):
    print(f"    !! servo {sid}: multi-turn not confirmed, read back {state}")
    return False
  return True


# ----------------------------------------------------------------------------- moving
def prepare(bus: Bus, sid: int):
  bus.write1(sid, TORQUE_ENABLE, 0, "torque off while configuring")
  bus.write1(sid, GOAL_ACC, MOVE_ACC, "gentle acceleration")
  bus.write2(sid, GOAL_SPEED, MOVE_SPEED, "slow")
  bus.write2(sid, TORQUE_LIMIT, int(TORQUE_LIMIT_PERCENT * 10), f"{TORQUE_LIMIT_PERCENT} % torque")
  bus.write1(sid, TORQUE_ENABLE, 1, "torque on")


def goto_ticks(bus: Bus, sid: int, target: int, step_deg: float) -> bool:
  """Drive to an absolute (multi-turn) tick position in steps of at most step_deg of hinge rotation."""
  start = 0 if bus.dry_run else bus.read2(sid, PRESENT_POSITION, signed=True)
  step_ticks = max(1, hinge_deg_to_ticks(step_deg))
  print(f"    at {ticks_to_hinge_deg(start):+.1f} deg ({start} ticks) -> target {ticks_to_hinge_deg(target):+.1f} deg "
        f"({target} ticks), {abs(target - start) / step_ticks:.1f} step(s) of <= {step_deg:.0f} deg")
  position = start
  while position != target:
    position += max(-step_ticks, min(step_ticks, target - position))
    bus.write2(sid, GOAL_POSITION, position, "waypoint")
    if bus.dry_run:
      continue
    deadline = time.time() + MOVE_TIMEOUT_S
    while time.time() < deadline:
      time.sleep(0.05)
      now = bus.read2(sid, PRESENT_POSITION, signed=True)
      if abs(now - position) <= POS_TOLERANCE_TICKS and bus.read1(sid, MOVING) == 0:
        break
    else:
      now = bus.read2(sid, PRESENT_POSITION, signed=True)
      print(f"    !! servo {sid}: timed out at {ticks_to_hinge_deg(now):+.1f} deg, load {bus.read2(sid, PRESENT_LOAD)}")
      bus.write1(sid, TORQUE_ENABLE, 0, "torque off after timeout")
      return False
  return True


def set_home(bus: Bus, sid: int) -> bool:
  """Redefine the present position as zero by writing the position-offset register."""
  bus.write1(sid, TORQUE_ENABLE, 0, "torque off: the hinge must stay where it is")
  raw = 0 if bus.dry_run else bus.read2(sid, PRESENT_POSITION, signed=True)
  offset = bus.read2(sid, POSITION_OFFSET, signed=True) if not bus.dry_run else 0
  new_offset = offset - raw
  print(f"    present {raw} ticks ({ticks_to_hinge_deg(raw):+.1f} deg), offset {offset} -> {new_offset}")
  bus.write1(sid, EEPROM_LOCK, 0, "unlock EEPROM")
  bus.write2(sid, POSITION_OFFSET, new_offset, "current position becomes zero")
  bus.write1(sid, EEPROM_LOCK, 1, "lock EEPROM")
  if bus.dry_run:
    return True
  time.sleep(0.05)
  now = bus.read2(sid, PRESENT_POSITION, signed=True)
  if abs(now) > POS_TOLERANCE_TICKS:
    print(f"    !! servo {sid}: reads {now} ticks ({ticks_to_hinge_deg(now):+.1f} deg) after homing, expected ~0. "
          f"Your firmware may not apply reg {POSITION_OFFSET} this way; check the memory table.")
    return False
  return True


# ----------------------------------------------------------------------------- report / main
def range_note(pos: int) -> str:
  """Warning text if a position is near or past the representable multi-turn range."""
  if abs(pos) > MULTITURN_TICK_LIMIT:
    return (f"  !! {pos} ticks is outside the +-{MULTITURN_TICK_LIMIT} multi-turn range: the reading has aliased. "
            f"Unwind this hinge by hand before zeroing.")
  if abs(pos) > MULTITURN_TICK_LIMIT * RANGE_WARN_FRACTION:
    return f"  ! {pos} ticks is within {100 - RANGE_WARN_FRACTION * 100:.0f} % of the multi-turn limit"
  return ""


def report(bus: Bus, sid: int) -> dict:
  state = multiturn_state(bus, sid)
  pos = bus.read2(sid, PRESENT_POSITION, signed=True)
  return dict(id=sid, pos_ticks=pos, hinge_deg=ticks_to_hinge_deg(pos),
              turns=pos / TICKS_PER_TURN / GEAR_RATIO, volts=bus.read1(sid, PRESENT_VOLTAGE) / 10,
              temp=bus.read1(sid, PRESENT_TEMPERATURE), multiturn=multiturn_ok(state), **state)


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--port", required=True, help="serial port, e.g. COM5 or /dev/ttyUSB0")
  ap.add_argument("--baud", type=int, default=BAUD)
  ap.add_argument("--ids", type=int, nargs="*", default=IDS, help="servo IDs (default 1..27)")
  ap.add_argument("--mode", choices=("goto", "set-home"), default="goto")
  ap.add_argument("--execute", action="store_true", help="actually write and move (default: dry run)")
  ap.add_argument("--yes", action="store_true", help="do not ask before each servo")
  ap.add_argument("--scan", action="store_true", help="report every servo and exit")
  ap.add_argument("--enable-multiturn", action="store_true", help="write the multi-turn configuration first")
  ap.add_argument("--check-multiturn", action="store_true", help="refuse to move a servo that is not in multi-turn")
  ap.add_argument("--step-deg", type=float, default=STEP_DEG_DEFAULT, help="max hinge degrees per goal command")
  a = ap.parse_args()

  bus = Bus(a.port, a.baud, dry_run=not a.execute)
  if not a.execute:
    print("DRY RUN: no writes are sent. Add --execute to move the hardware.\n")
  ok, failed = [], []
  try:
    print(f"scanning {len(a.ids)} IDs on {a.port} @ {a.baud} ...")
    found = []
    for sid in a.ids:
      model = bus.ping(sid)
      if model is None:
        print(f"  servo {sid:2d}: NO RESPONSE")
        failed.append(sid)
        continue
      r = report(bus, sid)
      found.append(sid)
      note = range_note(r["pos_ticks"])
      print(f"  servo {sid:2d}: model {model}, {r['hinge_deg']:+8.1f} deg hinge ({r['turns']:+.2f} hinge turns, "
            f"{r['pos_ticks']:+6d} ticks), offset {r['offset']:+5d}, mode {r['mode']}, "
            f"limits {r['min_limit']}/{r['max_limit']} -> multi-turn {'YES' if r['multiturn'] else 'NO'}, "
            f"{r['volts']:.1f} V, {r['temp']} C{note}")
    if a.scan:
      return 0 if not failed else 1
    if failed:
      print(f"\n{len(failed)} servo(s) did not answer: {failed}. Fix the bus before zeroing.")
      return 1

    for sid in found:
      print(f"\nservo {sid}:")
      if a.enable_multiturn:
        if not enable_multiturn(bus, sid):
          failed.append(sid)
          continue
      elif a.check_multiturn and not multiturn_ok(multiturn_state(bus, sid)):
        print(f"    !! servo {sid} is not in multi-turn; run with --enable-multiturn")
        failed.append(sid)
        continue
      if a.execute and not a.yes:
        answer = input(f"    {'drive to zero' if a.mode == 'goto' else 'set current position as zero'}"
                       f" for servo {sid}? [y/N/q] ").strip().lower()
        if answer == "q":
          break
        if answer != "y":
          print("    skipped")
          continue
      if a.mode == "goto":
        pos = bus.read2(sid, PRESENT_POSITION, signed=True) if a.execute else 0
        if abs(pos) > MULTITURN_TICK_LIMIT:
          print(f"    !! servo {sid}: {range_note(pos).strip()}")
          failed.append(sid)
          continue
        prepare(bus, sid)
        good = goto_ticks(bus, sid, 0, a.step_deg)
        bus.write1(sid, TORQUE_ENABLE, 0, "torque off: hinge is free again")
      else:
        good = set_home(bus, sid)
      (ok if good else failed).append(sid)
      print(f"    {'done' if good else 'FAILED'}")
  except KeyboardInterrupt:
    print("\ninterrupted: disabling torque on every servo")
    for sid in a.ids:
      try:
        bus.write1(sid, TORQUE_ENABLE, 0)
      except IOError:
        pass
    return 130
  finally:
    bus.close()

  print(f"\n{len(ok)} servo(s) zeroed{' (dry run)' if not a.execute else ''}, {len(failed)} failed: {failed or 'none'}")
  return 0 if not failed else 1


if __name__ == "__main__":
  sys.exit(main())
