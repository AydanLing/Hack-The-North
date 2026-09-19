"""File-backed checked-shape library with explicit human picks."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .records import ShapeRecord

STATUS_ORDER = ("proposed", "threadable", "planned", "checked", "picked")


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise ValueError("shape name must contain a letter or digit")
    return slug


class Library:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.root / f"{_slug(name)}.json"

    def entries(self) -> list[dict[str, Any]]:
        return [json.loads(path.read_text()) for path in sorted(self.root.glob("*.json"))]

    def _index(self, *, exclude: str | None = None) -> dict[str, str]:
        index: dict[str, str] = {}
        for entry in self.entries():
            if exclude is not None and _slug(entry["name"]) == _slug(exclude):
                continue
            for alias in [entry["name"], *entry.get("aliases", [])]:
                normalized = alias.casefold().strip()
                if normalized in index:
                    raise ValueError(f"duplicate library alias {alias!r}")
                index[normalized] = entry["name"]
        return index

    def add(self, record: ShapeRecord | dict[str, Any], *, replace: bool = False) -> Path:
        payload = asdict(record) if isinstance(record, ShapeRecord) else dict(record)
        name = str(payload["name"])
        target = self._path(name)
        if target.exists() and not replace:
            raise FileExistsError(f"library entry {name!r} already exists")
        existing = self._index(exclude=name)
        for alias in [name, *payload.get("aliases", [])]:
            if alias.casefold().strip() in existing:
                raise ValueError(f"alias {alias!r} belongs to {existing[alias.casefold().strip()]!r}")
        target.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
        return target

    def get(self, name_or_alias: str) -> dict[str, Any]:
        normalized = name_or_alias.casefold().strip()
        for entry in self.entries():
            aliases = [entry["name"], *entry.get("aliases", [])]
            if any(alias.casefold().strip() == normalized for alias in aliases):
                return entry
        raise KeyError(name_or_alias)

    def set_status(self, name: str, status: str) -> Path:
        if status not in STATUS_ORDER:
            raise ValueError(f"unknown status {status!r}")
        entry = self.get(name)
        current = STATUS_ORDER.index(entry["status"])
        requested = STATUS_ORDER.index(status)
        if requested > current + 1:
            raise ValueError(f"cannot skip from {entry['status']} to {status}")
        entry["status"] = status
        return self.add(entry, replace=True)

    def pick(self, names: Iterable[str], *, replace: bool = False) -> list[Path]:
        selected = {name.casefold().strip() for name in names}
        changed: list[Path] = []
        for entry in self.entries():
            aliases = {entry["name"].casefold(), *(alias.casefold() for alias in entry.get("aliases", []))}
            is_selected = bool(selected & aliases)
            if is_selected or replace:
                entry["human_pick"] = is_selected
                if is_selected and STATUS_ORDER.index(entry["status"]) >= STATUS_ORDER.index("checked"):
                    entry["status"] = "picked"
                changed.append(self.add(entry, replace=True))
        unresolved = selected - {
            alias.casefold()
            for entry in self.entries()
            for alias in [entry["name"], *entry.get("aliases", [])]
        }
        if unresolved:
            raise KeyError(f"unknown picks: {', '.join(sorted(unresolved))}")
        return changed

