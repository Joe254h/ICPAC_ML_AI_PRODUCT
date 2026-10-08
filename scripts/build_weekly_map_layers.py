"""Build cartography/weekly_map_layers.geojson, the reference-style map's extra lines.

The ICPAC weekly bulletin maps (templates/icpac_weekly_reference.docx) draw, besides the
black GHA boundaries, thin grey coastlines (no other countries' borders) and the shores
of Lakes Victoria, Tanganyika and Malawi, and Somalia's regions on the Somalia map. Those
lines come from Natural Earth (public domain, https://www.naturalearthdata.com):

    ne_50m_coastline.geojson, ne_50m_lakes.geojson and
    ne_10m_admin_1_states_provinces.geojson from
    https://github.com/nvkelso/natural-earth-vector/tree/master/geojson

Usage: python scripts/build_weekly_map_layers.py <directory with those three files>
"""

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "cartography" / "weekly_map_layers.geojson"
LAKES = {"Lake Victoria", "Lake Tanganyika", "Lake Malawi"}
WINDOW = (17.0, 56.0, -16.0, 27.0)  # west, east, south, north: the region map plus margin
MIN_RING_AREA = 0.05  # square degrees; drops islets the reference does not draw
TOLERANCE = 0.01  # degrees, Douglas-Peucker


def rings(geometry: dict) -> list[np.ndarray]:
    polygons = (
        [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    )
    return [np.asarray(ring, dtype=float)[:, :2] for polygon in polygons for ring in polygon]


def area(ring: np.ndarray) -> float:
    x, y = ring[:, 0], ring[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2


def simplify(points: np.ndarray, tolerance: float = TOLERANCE) -> np.ndarray:
    """Douglas-Peucker, iterative so long coastlines need no deep recursion."""
    if len(points) < 3:
        return points
    keep = np.zeros(len(points), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        start, end = points[first], points[last]
        direction = end - start
        norm = float(np.hypot(*direction))
        offsets = points[first + 1 : last] - start
        distances = (
            np.abs(direction[0] * offsets[:, 1] - direction[1] * offsets[:, 0]) / norm
            if norm
            else np.hypot(offsets[:, 0], offsets[:, 1])
        )
        index = int(np.argmax(distances))
        if distances[index] > tolerance:
            middle = first + 1 + index
            keep[middle] = True
            stack += [(first, middle), (middle, last)]
    return points[keep]


def inside(points: np.ndarray) -> np.ndarray:
    west, east, south, north = WINDOW
    x, y = points[:, 0], points[:, 1]
    return (x >= west) & (x <= east) & (y >= south) & (y <= north)


def window_runs(ring: np.ndarray) -> list[np.ndarray]:
    """Pieces of a ring inside the window, each with one vertex beyond it on each side."""
    keep = inside(ring)
    keep = keep | np.roll(keep, 1) | np.roll(keep, -1)
    if keep.all():
        return [ring]
    runs, current = [], []
    for point, flag in zip(ring, keep, strict=True):
        if flag:
            current.append(point)
        elif current:
            runs.append(np.asarray(current))
            current = []
    if current:
        runs.append(np.asarray(current))
    return [run for run in runs if len(run) > 1]


def line(coordinates: np.ndarray) -> list[list[float]]:
    return [[round(float(x), 3), round(float(y), 3)] for x, y in coordinates]


def shared_edges(polygons: list[list[np.ndarray]]) -> list[np.ndarray]:
    """Boundaries between neighbouring regions: edges that two polygons have in common."""
    edges: Counter = Counter()
    for polygon in polygons:
        for ring in polygon:
            points = [tuple(np.round(p, 6)) for p in ring]
            for a, b in zip(points, points[1:], strict=False):
                edges[tuple(sorted((a, b)))] += 1
    internal = {edge for edge, count in edges.items() if count > 1}
    neighbours: dict = {}
    for a, b in internal:
        neighbours.setdefault(a, []).append(b)
        neighbours.setdefault(b, []).append(a)
    seen: set = set()
    chains = []
    ends = [p for p, n in neighbours.items() if len(n) != 2] or list(neighbours)
    for start in ends + list(neighbours):
        for following in neighbours[start]:
            edge = tuple(sorted((start, following)))
            if edge in seen:
                continue
            chain, previous, current = [start], start, following
            seen.add(edge)
            while True:
                chain.append(current)
                options = [
                    p
                    for p in neighbours[current]
                    if p != previous and tuple(sorted((current, p))) not in seen
                ]
                if len(neighbours[current]) != 2 or not options:
                    break
                seen.add(tuple(sorted((current, options[0]))))
                previous, current = current, options[0]
            chains.append(np.asarray(chain))
    return chains


def main(source: Path) -> None:
    features = []
    coast = json.loads((source / "ne_50m_coastline.geojson").read_text())
    for feature in coast["features"]:
        geometry = feature["geometry"]
        parts = (
            [geometry["coordinates"]]
            if geometry["type"] == "LineString"
            else geometry["coordinates"]
        )
        for part in parts:
            points = np.asarray(part, dtype=float)[:, :2]
            closed = len(points) > 3 and np.allclose(points[0], points[-1])
            if closed and area(points) < MIN_RING_AREA:
                continue
            for run in window_runs(points):
                features.append(("coast", "coastline", simplify(run)))
    lakes = json.loads((source / "ne_50m_lakes.geojson").read_text())
    for feature in lakes["features"]:
        name = feature["properties"].get("name")
        if name in LAKES:
            for ring in rings(feature["geometry"]):
                if area(ring) >= MIN_RING_AREA:
                    features.append(("lake", name, simplify(ring)))
    regions = json.loads((source / "ne_10m_admin_1_states_provinces.geojson").read_text())
    somalia = [
        rings(f["geometry"])
        for f in regions["features"]
        if f["properties"].get("adm0_a3") in {"SOM", "SOL"}
    ]
    for chain in shared_edges(somalia):
        features.append(("admin1", "Somalia", simplify(chain)))
    collection = {
        "type": "FeatureCollection",
        "source": "Natural Earth (public domain): ne_50m_coastline, ne_50m_lakes, "
        "ne_10m_admin_1_states_provinces; built by scripts/build_weekly_map_layers.py",
        "features": [
            {
                "type": "Feature",
                "properties": {"role": role, "name": name},
                "geometry": {"type": "LineString", "coordinates": line(points)},
            }
            for role, name, points in features
            if len(points) > 1
        ],
    }
    OUTPUT.write_text(json.dumps(collection, separators=(",", ":")) + "\n", encoding="utf-8")
    roles = Counter(f["properties"]["role"] for f in collection["features"])
    print(f"Wrote {OUTPUT.relative_to(ROOT)}: {dict(roles)}, {OUTPUT.stat().st_size} bytes")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
