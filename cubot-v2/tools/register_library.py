#!/usr/bin/env python3
"""Register picked exploration winners in the file-backed icon library.

After the blind pick, ``tools/explore_summary.py --only <picks> [--prefer ...]``
writes a ``handoff-manifest.json`` holding exactly the chosen loose-passing
runs.  This tool copies each run's exact target mask into
``data/library/<category>/<name>.txt`` with an alias header, so
``cubot.generate.parametric`` serves it like any registered icon
(``cubot pipeline <name>`` can re-fold it) and the registry test threads it on
every run.  Categories and aliases come from ``data/library-concepts.json``.

Usage (from ``cubot-v2/``)::

    uv run python tools/register_library.py --manifest out/library-20260919/handoff-manifest.json
    uv run python tools/register_library.py --manifest ... --only cat dog sun --dry-run

Names already registered by hand in ``parametric._PATTERNS`` and aliases that
collide with an existing icon name or alias are refused, never overwritten;
``--replace`` allows re-registering a name that is already in the library.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cubot.generate import parametric  # noqa: E402

CONCEPTS_PATH = ROOT / "data" / "library-concepts.json"


def normalise(alias: str) -> str:
    return alias.strip().lower().replace("_", "-").replace(" ", "-")


def load_concepts(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    return {entry["name"]: entry for entry in json.loads(path.read_text())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=None, metavar="NAME")
    parser.add_argument("--concepts", type=Path, default=CONCEPTS_PATH)
    parser.add_argument("--library", type=Path, default=parametric.LIBRARY_ROOT)
    parser.add_argument("--category", default="misc", help="category for names missing from the concepts file")
    parser.add_argument("--replace", action="store_true", help="overwrite entries already in the library")
    parser.add_argument("--skip-registered", action="store_true",
                        help="skip (with a note) names already hand-registered in parametric._PATTERNS instead of aborting")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    if manifest.get("schema") != "cubot.handoff.manifest.v1":
        raise SystemExit(f"{args.manifest}: not a cubot.handoff.manifest.v1 manifest")
    concepts = load_concepts(args.concepts)
    hand_names = set(parametric.ICON_NAMES) - set(parametric.LIBRARY_NAMES)
    taken_aliases = {alias: name for alias, name in parametric._ALIASES.items()}
    library_names = set(parametric.LIBRARY_NAMES)

    only = None if args.only is None else {normalise(n) for n in args.only}
    shapes = [s for s in manifest["shapes"] if only is None or s["name"] in only]
    if only is not None:
        missing = sorted(only - {s["name"] for s in shapes})
        if missing:
            raise SystemExit(f"--only names not in the manifest: {', '.join(missing)}")

    written = []
    for shape in shapes:
        name = normalise(shape["name"])
        run_dir = Path(shape["run"])
        if not run_dir.is_absolute():
            run_dir = args.manifest.parent / run_dir
        record = json.loads((run_dir / "record.json").read_text())
        rows = list(record["target"])
        if sum(row.count("#") for row in rows) != 27:
            raise SystemExit(f"{name}: record target is not a 27-cell mask")
        if name in hand_names:
            if args.skip_registered:
                print(f"  {name}: already hand-registered in parametric._PATTERNS; skipped")
                continue
            raise SystemExit(f"{name}: already registered by hand in parametric._PATTERNS; edit that entry instead")
        if name in library_names and not args.replace:
            raise SystemExit(f"{name}: already in the library (use --replace)")
        concept = concepts.get(name, {})
        aliases = []
        for alias in concept.get("aliases", []):
            alias = normalise(alias)
            if not alias or alias == name:
                continue
            owner = taken_aliases.get(alias)
            if alias in hand_names or (owner is not None and owner != name):
                print(f"  {name}: alias {alias!r} already belongs to {owner or alias!r}; dropped")
                continue
            aliases.append(alias)
        category = concept.get("category", args.category)
        path = args.library / category / f"{name}.txt"
        header = [f"// aliases: {', '.join(aliases)}" if aliases else "// aliases:",
                  f"// variant: {shape.get('variant', '')}",
                  f"// source: {run_dir.name}; moves {shape.get('moves')}; ends_flat {shape.get('ends_flat')}"]
        text = "\n".join(header + rows) + "\n"
        print(f"{'would write' if args.dry_run else 'write'} {path} ({len(aliases)} aliases)")
        if not args.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        written.append(path)
        for alias in aliases:
            taken_aliases[alias] = name
        library_names.add(name)
    print(f"{len(written)} shapes {'checked' if args.dry_run else 'registered'} under {args.library}")
    if written and not args.dry_run:
        # Re-load through the real loader so collisions surface here, not at the next import.
        parametric.load_library(args.library)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
