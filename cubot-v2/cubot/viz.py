"""Small dependency-light renders used for human recognition review."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Literal, Sequence

from PIL import Image, ImageDraw, ImageFont

from .records import Cell
from .shapes import planar_projection

COLORS = ((43, 108, 176), (236, 112, 72))
SILHOUETTE = (33, 39, 46)
BACKGROUND = (248, 247, 243)


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def render_top(
    cells: Sequence[Cell],
    out_path: str | Path,
    *,
    cell_px: int = 54,
    margin: int = 36,
    numbered: bool = False,
    style: Literal["modules", "silhouette"] = "modules",
    transform: str = "identity",
) -> Path:
    """Render a planar path for engineering or recognition review.

    ``modules`` preserves the alternating module colors and optional path
    indices.  ``silhouette`` merges the cells into one uncluttered dark shape;
    it intentionally contains neither per-cell outlines nor path numbers.
    ``transform`` can apply the symmetry selected by the matcher so reviewers
    see the candidate in the target's canonical orientation.
    """

    if not cells:
        raise ValueError("cannot render an empty path")
    if style not in {"modules", "silhouette"}:
        raise ValueError(f"unknown top render style {style!r}")
    if style == "silhouette" and numbered:
        raise ValueError("silhouette renders cannot contain per-cell numbers")
    projected = _transform_points(planar_projection(cells), transform)
    xs = [cell[0] for cell in projected]
    ys = [cell[1] for cell in projected]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = (max_x - min_x + 1) * cell_px + 2 * margin
    height = (max_y - min_y + 1) * cell_px + 2 * margin
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = _font(max(10, cell_px // 4))
    for index, (x, y) in enumerate(projected):
        x0 = margin + (x - min_x) * cell_px
        y0 = margin + (max_y - y) * cell_px
        if style == "silhouette":
            draw.rectangle((x0, y0, x0 + cell_px, y0 + cell_px), fill=SILHOUETTE)
            continue
        box = (x0 + 2, y0 + 2, x0 + cell_px - 2, y0 + cell_px - 2)
        draw.rounded_rectangle(box, radius=max(2, cell_px // 9), fill=COLORS[index % 2], outline=(20, 30, 35), width=2)
        if numbered:
            label = str(index)
            draw.text((x0 + cell_px / 2, y0 + cell_px / 2), label, font=font, fill="white", anchor="mm")
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return target


def _transform_points(points: Sequence[tuple[int, int]], transform: str) -> tuple[tuple[int, int], ...]:
    reflected = transform.startswith("mirror-")
    name = transform.removeprefix("mirror-")
    if name not in {"identity", "rot90", "rot180", "rot270"}:
        raise ValueError(f"unknown planar transform {transform!r}")
    result: list[tuple[int, int]] = []
    for x, y in points:
        if reflected:
            x = -x
        if name == "rot90":
            x, y = -y, x
        elif name == "rot180":
            x, y = -x, -y
        elif name == "rot270":
            x, y = y, -x
        result.append((x, y))
    return tuple(result)


def render_silhouette(
    cells: Sequence[Cell],
    out_path: str | Path,
    *,
    cell_px: int = 54,
    margin: int = 36,
    transform: str = "identity",
) -> Path:
    """Render an uncluttered single-color silhouette for blind review."""

    return render_top(
        cells,
        out_path,
        cell_px=cell_px,
        margin=margin,
        style="silhouette",
        transform=transform,
    )


def render_iso(
    cells: Sequence[Cell],
    out_path: str | Path,
    *,
    scale: int = 34,
    margin: int = 60,
) -> Path:
    if not cells:
        raise ValueError("cannot render an empty path")

    def project(cell: Cell) -> tuple[float, float]:
        x, y, z = cell
        return ((x - y) * scale * 0.85, (x + y) * scale * 0.43 - z * scale)

    points = [project(cell) for cell in cells]
    min_x = min(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_x = max(point[0] for point in points)
    max_y = max(point[1] for point in points)
    image = Image.new(
        "RGB",
        (int(max_x - min_x + 2 * margin + scale), int(max_y - min_y + 2 * margin + scale)),
        (248, 247, 243),
    )
    draw = ImageDraw.Draw(image)
    order = sorted(range(len(cells)), key=lambda index: sum(cells[index]))
    for index in order:
        px, py = points[index]
        cx = px - min_x + margin
        cy = py - min_y + margin
        r = scale * 0.48
        top = [(cx, cy - r), (cx + r, cy - r / 2), (cx, cy), (cx - r, cy - r / 2)]
        left = [(cx - r, cy - r / 2), (cx, cy), (cx, cy + r), (cx - r, cy + r / 2)]
        right = [(cx + r, cy - r / 2), (cx, cy), (cx, cy + r), (cx + r, cy + r / 2)]
        color = COLORS[index % 2]
        draw.polygon(left, fill=tuple(max(0, c - 45) for c in color), outline=(25, 25, 25))
        draw.polygon(right, fill=tuple(max(0, c - 20) for c in color), outline=(25, 25, 25))
        draw.polygon(top, fill=color, outline=(25, 25, 25))
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return target


def render_voxels(
    cells: Sequence[Cell],
    out_path: str | Path,
    *,
    scale: int = 28,
    margin: int = 40,
    yaw_quarter_turns: int = 0,
) -> Path:
    """Solid isometric voxel render (touching cubes, painter's order) for 3D shells.

    :func:`render_iso` draws exploded module icons, which is right for a flat
    drawing's engineering view but unreadable for a one-deep 3D shell.  Here
    the viewer looks down the (+1, +1, +1) direction: the +x, +y and +z faces
    are visible, cubes are drawn back to front, and the whole thing is one
    two-tone body (alternating modules) so the silhouette reads first.
    ``yaw_quarter_turns`` rotates the shape about +z before projecting.
    """

    if not cells:
        raise ValueError("cannot render an empty path")
    pts = [tuple(int(v) for v in cell) for cell in cells]
    for _ in range(yaw_quarter_turns % 4):
        pts = [(-y, x, z) for x, y, z in pts]
    min_corner = tuple(min(p[i] for p in pts) for i in range(3))
    pts = [(x - min_corner[0], y - min_corner[1], z - min_corner[2]) for x, y, z in pts]
    a, b, c = scale * 0.866, scale * 0.5, float(scale)

    def project(x: float, y: float, z: float) -> tuple[float, float]:
        return ((x - y) * a, (x + y) * b - z * c)

    corners = [project(x + dx, y + dy, z + dz) for x, y, z in pts for dx in (0, 1) for dy in (0, 1) for dz in (0, 1)]
    min_x = min(px for px, _ in corners)
    min_y = min(py for _, py in corners)
    max_x = max(px for px, _ in corners)
    max_y = max(py for _, py in corners)
    image = Image.new("RGB", (int(max_x - min_x + 2 * margin), int(max_y - min_y + 2 * margin)), (248, 247, 243))
    draw = ImageDraw.Draw(image)

    def screen(x: float, y: float, z: float) -> tuple[float, float]:
        px, py = project(x, y, z)
        return (px - min_x + margin, py - min_y + margin)

    order = sorted(range(len(pts)), key=lambda index: sum(pts[index]))
    for index in order:
        x, y, z = pts[index]
        base = COLORS[index % 2]
        top = [screen(x, y, z + 1), screen(x + 1, y, z + 1), screen(x + 1, y + 1, z + 1), screen(x, y + 1, z + 1)]
        face_x = [screen(x + 1, y, z), screen(x + 1, y + 1, z), screen(x + 1, y + 1, z + 1), screen(x + 1, y, z + 1)]
        face_y = [screen(x, y + 1, z), screen(x + 1, y + 1, z), screen(x + 1, y + 1, z + 1), screen(x, y + 1, z + 1)]
        draw.polygon(face_y, fill=tuple(max(0, v - 60) for v in base), outline=(30, 30, 30))
        draw.polygon(face_x, fill=tuple(max(0, v - 25) for v in base), outline=(30, 30, 30))
        draw.polygon(top, fill=base, outline=(30, 30, 30))
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return target


def contact_sheet(
    entries: Iterable[tuple[str, str | Path]],
    out_path: str | Path,
    *,
    columns: int = 4,
    tile: tuple[int, int] = (320, 360),
    show_labels: bool = True,
) -> Path:
    """Build a numbered sheet; hide concept labels for blind recognition tests."""

    materialized = list(entries)
    if not materialized:
        raise ValueError("contact sheet needs at least one entry")
    rows = (len(materialized) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * tile[0], rows * tile[1]), "white")
    draw = ImageDraw.Draw(canvas)
    font = _font(20)
    for index, (label, path) in enumerate(materialized, start=1):
        image = Image.open(path).convert("RGB")
        image.thumbnail((tile[0] - 24, tile[1] - 54))
        col = (index - 1) % columns
        row = (index - 1) // columns
        left = col * tile[0]
        top = row * tile[1]
        x = left + (tile[0] - image.width) // 2
        y = top + 40 + (tile[1] - 50 - image.height) // 2
        canvas.paste(image, (x, y))
        heading = f"{index}. {label}" if show_labels else str(index)
        draw.text((left + 12, top + 10), heading, fill="black", font=font)
        draw.rectangle((left, top, left + tile[0] - 1, top + tile[1] - 1), outline=(190, 190, 190))
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target)
    return target
