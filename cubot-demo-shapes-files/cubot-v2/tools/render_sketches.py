"""Render the fitted sketch targets for recognition review.

Threading a mask proves it is reachable, not that it still looks like the thing
it was drawn from -- the variant search walks away from the sketch to find a
threadable pose, and how far it walked is exactly how much likeness it ate.
That call has to be made by eye, so this emits the same artefacts the pipeline
uses for it: a clean silhouette and an isometric per shape, a labelled contact
sheet, and a blind one with the names hidden.

    uv run python tools/render_sketches.py

Reads docs/sketches/threadable-targets.txt, writes docs/sketches/renders/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cubot.config import load_machine
from cubot.solver import solve
from cubot.viz import contact_sheet, render_iso, render_silhouette

from sketch_fit import cells_of, parse_blocks


def threaded_path(cells, roll: str):
    """The chain order the solver threads this mask with, for a faithful render."""
    result = solve([(x, y, 0) for (x, y) in cells], roll, budget_nodes=2_000_000)
    if not result.solutions:
        return None
    return [tuple(cell) for cell in result.solutions[0].path]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--targets", type=Path,
                        default=root / "docs/sketches/threadable-targets.txt")
    parser.add_argument("--out", type=Path, default=root / "docs/sketches/renders")
    parser.add_argument("--roll", help="override the machine roll word")
    args = parser.parse_args()

    roll = args.roll or load_machine().roll
    args.out.mkdir(parents=True, exist_ok=True)

    entries: list[tuple[str, Path]] = []
    missing: list[str] = []
    for heading, rows in parse_blocks(args.targets):
        name = heading.split()[0]
        path = threaded_path(cells_of(rows), roll)
        if path is None:
            missing.append(name)
            print(f"  {name}: does NOT thread -- skipped", file=sys.stderr)
            continue
        silhouette = render_silhouette(path, args.out / f"{name}-silhouette.png")
        render_iso(path, args.out / f"{name}-iso.png")
        entries.append((name, silhouette))
        print(f"  {name}: rendered", file=sys.stderr)

    if entries:
        contact_sheet(entries, args.out / "contact-sheet-labeled.png", show_labels=True)
        contact_sheet(entries, args.out / "contact-sheet-blind.png", show_labels=False)
        print(f"{len(entries)} shapes rendered to {args.out}", file=sys.stderr)
    if missing:
        print(f"WARNING: {len(missing)} did not thread: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
