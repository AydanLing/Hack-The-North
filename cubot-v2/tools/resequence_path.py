#!/usr/bin/env python3
"""Re-order an existing fold path so it reads as a clean progressive fold.

A shipped path can already be minimal in move COUNT (one detent per joint that
finishes off-zero) and still look chaotic, because move count says nothing about
move ORDER.  Moving joint i swings one whole side of the chain; if the joints on
that side are still flat, a long straight arm sweeps through the air and then
gets folded up afterwards.  Doing the far joints first means the same detent
swings a short, already-folded stub instead.

The goal states are fixed, so the move multiset is fixed too: this only permutes
it (and re-picks each move's swinging side).  Cost per move is the number of
modules on the swinging side whose joints have not reached their goal yet --
"how much unfolded structure did this move throw around".  Ties break on peak
torque.  Every prefix is validated with the real checker, and the winning order
is replayed end to end, so a re-ordered path is feasible or it is not reported.

    python tools/resequence_path.py handoff-17/shapes/01-heart/path.json
    python tools/resequence_path.py <path.json> --machine config/machine-17.toml --write out.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from cubot.config import load_machine, load_profile
from cubot.folder import check_move, goal_reached, next_pose, replay
from cubot.records import Move, Pose

SIDES: tuple[str, ...] = ("in", "out")


def moving_modules(joint: int, side: str, n_joints: int) -> list[int]:
    """Modules that physically swing for this move.

    Per the handoff conventions: side 'out' swings the tail (modules
    joint+1..N-1), side 'in' swings the base (modules 0..joint-1).
    """
    if side == "out":
        return list(range(joint + 1, n_joints + 1))
    return list(range(0, joint))


def swing_cost(joint: int, side: str, states: list[int], goal: list[int]) -> int:
    """Unfolded modules thrown around by this move.

    A module counts when the joint inside it still has to move later: that is
    the straight material we would rather fold before we swing it.
    """
    n_joints = len(goal)
    cost = 0
    for module in moving_modules(joint, side, n_joints):
        # Joint index j lives inside module j, so a swinging module carries a
        # pending fold when its own joint has not reached goal yet.
        if module < n_joints and states[module] != goal[module]:
            cost += 1
    return cost


def peak_nm(report) -> float:
    meas = getattr(report, "measurements", None) or {}
    return float(meas.get("peak_demand_nm") or 0.0)


def resequence(start: Pose, goal: Pose, machine, profile, *, beam: int = 240):
    """Beam-search a permutation of the goal's detents, cheapest swing first."""
    goal_states = list(goal.states)
    pending = [j for j, s in enumerate(goal_states) if s != 0]

    # A beam entry is (cum_cost, cum_peak, pose, moves, remaining).
    beams = [(0, 0.0, start, [], tuple(pending))]
    for _ in range(len(pending)):
        nxt = []
        for cum_cost, cum_peak, pose, moves, remaining in beams:
            states = list(pose.states)
            for joint in remaining:
                delta = goal_states[joint] - states[joint]
                if delta == 0:
                    continue
                step = 1 if delta > 0 else -1
                for side in SIDES:
                    move = Move(joint, step, side, machine.move_time_s)
                    report = check_move(pose, move, machine, profile)
                    if not report.hard_ok:
                        continue
                    cost = swing_cost(joint, side, states, goal_states)
                    # An 'in' move re-orients module zero, so the base index has
                    # to come from mechanics rather than a states-only copy.
                    after = next_pose(pose, move)
                    nxt.append((
                        cum_cost + cost,
                        cum_peak + peak_nm(report),
                        after,
                        moves + [move],
                        tuple(j for j in remaining if j != joint),
                    ))
        if not nxt:
            return []
        nxt.sort(key=lambda e: (e[0], e[1]))
        beams = nxt[:beam]
    return beams


def describe(moves) -> str:
    return " ".join(f"j{m.joint}{m.delta:+d}/{m.side}" for m in moves)


def report_cost(moves, goal_states: list[int], n_joints: int) -> tuple[int, int]:
    """Total and worst unfolded-swing cost for a finished order."""
    states = [0] * n_joints
    total = worst = 0
    for m in moves:
        c = swing_cost(m.joint, m.side, states, goal_states)
        total += c
        worst = max(worst, c)
        states[m.joint] += m.delta
    return total, worst


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path_json", type=Path)
    ap.add_argument("--machine", default="config/machine-17.toml")
    ap.add_argument("--profile", default=None, help="default: the path's accept_profile")
    ap.add_argument("--beam", type=int, default=240)
    ap.add_argument("--write", type=Path, default=None,
                    help="write the re-ordered moves back out as JSON")
    args = ap.parse_args()

    doc = json.loads(args.path_json.read_text())
    machine = load_machine(args.machine)
    profile = load_profile(args.profile or doc["status"].get("accept_profile") or "loose")

    goal_states = list(doc["goal"]["states"])
    start = Pose(tuple(doc["start"]["states"]), machine.roll,
                 doc["start"].get("base", 0), doc["start"].get("lying"))
    goal = Pose(tuple(goal_states), machine.roll,
                doc["goal"].get("base", 0), doc["goal"].get("lying"))

    n_joints = len(goal_states)
    current = [Move(m["joint"], m["delta"], m["side"], machine.move_time_s)
               for m in doc["moves"]]
    cur_total, cur_worst = report_cost(current, goal_states, n_joints)
    print(f"{doc.get('name')}: {len(current)} moves, profile {profile.name if hasattr(profile,'name') else ''}")
    print(f"  current order : {describe(current)}")
    print(f"  current swing : total {cur_total}, worst {cur_worst}")

    beams = resequence(start, goal, machine, profile, beam=args.beam)
    if not beams:
        print("  no feasible re-ordering found")
        return 1

    for cum_cost, cum_peak, pose, moves, _ in beams[:1]:
        cand = replay(start, moves, goal=goal, machine=machine, profile=profile,
                      notes=("resequenced: progressive fold",))
        tot, worst = report_cost(moves, goal_states, n_joints)
        print(f"  new order     : {describe(moves)}")
        print(f"  new swing     : total {tot}, worst {worst}")
        print(f"  replay        : complete={cand.complete} hard_ok={cand.hard_ok} "
              f"violations={len(cand.violations)}")
        print(f"  scores        : { {k: round(v,3) for k,v in sorted(cand.scores.items())} }")
        if args.write and cand.complete and cand.hard_ok:
            args.write.write_text(json.dumps(
                [{"joint": m.joint, "delta": m.delta, "side": m.side} for m in moves],
                indent=2) + "\n")
            print(f"  wrote {args.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
