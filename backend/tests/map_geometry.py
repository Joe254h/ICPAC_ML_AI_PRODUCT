"""Measure the layout of a rendered map image (structural visual regression).

The same measurements run on the delivered ICPAC reference maps and on the platform's
renderings, so the tests compare geometry rather than pixels: map frames, the geographic
extent calibrated from the tick marks, the colourbar beside each frame, the logo box and
the position of the black country boundaries.
"""

from dataclasses import dataclass
from functools import cache

import numpy as np
from matplotlib import image as mpimg

TICKS_LON = np.arange(25.0, 51.0, 5.0)
TICKS_LAT = np.arange(-10.0, 21.0, 5.0)


@dataclass(frozen=True)
class Box:
    left: float
    right: float
    top: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


@dataclass(frozen=True)
class MapFrame:
    frame: Box
    extent: tuple[float, float, float, float]  # west, east, south, north
    px_per_deg: tuple[float, float]
    colourbar: Box | None
    logo: Box | None  # axes fraction: left, right, bottom (as top), top (as bottom)

    def to_lonlat(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        west, _, _, north = self.extent
        return west + (x - self.frame.left) / self.px_per_deg[0], north - (
            y - self.frame.top
        ) / self.px_per_deg[1]


@cache
def load(path) -> np.ndarray:
    """RGB in [0, 1]; cached, so callers must not modify the array."""
    img = mpimg.imread(path)
    return img[..., :3].astype(float)


def dark_pixels(rgb: np.ndarray, threshold: float = 0.3) -> np.ndarray:
    return rgb.max(axis=2) < threshold


def runs(line: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    padded = np.concatenate([[0], line.astype(np.int8), [0]])
    change = np.diff(padded)
    starts, ends = np.where(change == 1)[0], np.where(change == -1)[0]
    return [(int(s), int(e - 1)) for s, e in zip(starts, ends, strict=True) if e - s >= min_len]


def edges(dark: np.ndarray, min_len: int) -> list[tuple[float, int, int]]:
    """Straight dark segments along rows, merged across adjacent rows: (centre, start, end)."""
    found: list[list[tuple[int, int, int]]] = []
    for index, row in enumerate(dark):
        for start, end in runs(row, min_len):
            for group in found:
                i, s, e = group[-1]
                if index - i == 1 and abs(s - start) <= 3 and abs(e - end) <= 3:
                    group.append((index, start, end))
                    break
            else:
                found.append([(index, start, end)])
    return [
        (
            float(np.mean([g[0] for g in group])),
            int(np.median([g[1] for g in group])),
            int(np.median([g[2] for g in group])),
        )
        for group in found
    ]


def rectangles(dark: np.ndarray, min_width: int, min_height: int) -> list[Box]:
    """Axis frames: pairs of vertical edges closed by horizontal edges at top and bottom.

    Horizontal runs may extend past a corner (a tick at the end of a colourbar), so a
    side only needs to be covered by a horizontal edge, not matched exactly.
    """
    horizontal = edges(dark, min_width)
    vertical = edges(dark.T, min_height)

    def closed(y: float, left: float, right: float) -> float | None:
        for centre, start, end in horizontal:
            if abs(centre - y) <= 4 and start <= left + 4 and end >= right - 4:
                return centre
        return None

    boxes = []
    for i, (left, t1, b1) in enumerate(vertical):
        for right, t2, b2 in vertical[i + 1 :]:
            if right - left < min_width or abs(t1 - t2) > 4 or abs(b1 - b2) > 4:
                continue
            top, bottom = closed(min(t1, t2) + 1, left, right), closed(max(b1, b2) - 1, left, right)
            if top is not None and bottom is not None:
                boxes.append(Box(left, right, top, bottom))
    return boxes


def tick_positions(dark: np.ndarray, box: Box, axis: str) -> list[float]:
    """Centres of the tick marks just outside the bottom (x) or left (y) spine."""
    if axis == "x":
        band = dark[
            int(box.bottom) + 3 : int(box.bottom) + 9, int(box.left) + 3 : int(box.right) - 2
        ]
        hits = np.where(band.sum(axis=0) >= 4)[0] + int(box.left) + 3
    else:
        band = dark[int(box.top) + 3 : int(box.bottom) - 2, int(box.left) - 9 : int(box.left) - 3]
        hits = np.where(band.sum(axis=1) >= 4)[0] + int(box.top) + 3
    if not hits.size:
        return []
    groups = np.split(hits, np.where(np.diff(hits) > 2)[0] + 1)
    return [float(g.mean()) for g in groups]


def green(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 1] > rgb[..., 0] + 0.15) & (rgb[..., 1] > rgb[..., 2] + 0.05)


def logo_box(rgb: np.ndarray, frame: Box) -> Box | None:
    """Bounding box of the logo's green ink in the top-right of the frame (axes fraction).

    The search window lies over the sea and Arabia, outside the country union, so the
    mapped field (white there) cannot be mistaken for the logo.
    """
    x0, x1 = int(frame.left + 0.78 * frame.width), int(frame.left + 0.98 * frame.width)
    y0, y1 = int(frame.bottom - 0.97 * frame.height), int(frame.bottom - 0.76 * frame.height)
    ys, xs = np.nonzero(green(rgb[y0:y1, x0:x1]))
    if not ys.size:
        return None

    def fx(x: float) -> float:
        return (x - frame.left) / frame.width

    def fy(y: float) -> float:
        return (frame.bottom - y) / frame.height

    return Box(fx(xs.min() + x0), fx(xs.max() + 1 + x0), fy(ys.min() + y0), fy(ys.max() + 1 + y0))


def colourbar_beside(boxes: list[Box], frame: Box) -> Box | None:
    beside = [
        b
        for b in boxes
        if b.left > frame.right
        and b.width < 0.2 * frame.width
        and abs(b.top - frame.top) < 0.1 * frame.height
        and abs(b.bottom - frame.bottom) < 0.1 * frame.height
    ]
    return min(beside, key=lambda b: b.left) if beside else None


@cache
def measure(path) -> list[MapFrame]:
    """Every map frame in an image, ordered row by row."""
    rgb = load(path)
    dark = dark_pixels(rgb)
    height, width = dark.shape
    boxes = rectangles(dark, min_width=40, min_height=int(0.25 * height))
    frames = sorted(
        (b for b in boxes if b.width > 0.2 * width), key=lambda b: (round(b.top / 50), b.left)
    )
    maps = []
    for frame in frames:
        xs, ys = tick_positions(dark, frame, "x"), tick_positions(dark, frame, "y")
        if len(xs) != TICKS_LON.size or len(ys) != TICKS_LAT.size:
            raise AssertionError(f"expected 5-degree ticks, found {len(xs)} x and {len(ys)} y")
        ax, bx = np.polyfit(TICKS_LON, xs, 1)
        ay, by = np.polyfit(TICKS_LAT[::-1], ys, 1)
        extent = (
            (frame.left - bx) / ax,
            (frame.right - bx) / ax,
            (frame.bottom - by) / ay,
            (frame.top - by) / ay,
        )
        maps.append(
            MapFrame(
                frame,
                tuple(float(v) for v in extent),  # type: ignore[arg-type]
                (float(ax), float(-ay)),
                colourbar_beside(boxes, frame),
                logo_box(rgb, frame),
            )
        )
    return maps


def boundary_points(path, frame: MapFrame, logo_margin: float = 0.02) -> np.ndarray:
    """(lon, lat) of near-black pixels inside a frame: the country boundary lines."""
    rgb = load(path)
    box = frame.frame
    inner = rgb[int(box.top) + 4 : int(box.bottom) - 3, int(box.left) + 4 : int(box.right) - 3]
    ys, xs = np.nonzero(inner.max(axis=2) < 0.2)
    xs, ys = xs + int(box.left) + 4, ys + int(box.top) + 4
    if frame.logo is not None:
        fx = (xs - box.left) / box.width
        fy = (box.bottom - ys) / box.height
        logo = frame.logo
        outside = ~(
            (fx > logo.left - logo_margin)
            & (fx < logo.right + logo_margin)
            & (fy > logo.top - logo_margin)
            & (fy < logo.bottom + logo_margin)
        )
        xs, ys = xs[outside], ys[outside]
    lon, lat = frame.to_lonlat(xs.astype(float), ys.astype(float))
    return np.column_stack([lon, lat])
