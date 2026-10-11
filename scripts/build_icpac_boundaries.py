"""Build cartography/icpac11_adm0.geojson, the country outlines every map draws.

The HPC package's cartography/east_africa_11_adm0.geojson (kept unchanged, it is in the
package checksums) ends Sudan along 22 degrees N: it leaves out the Halaib triangle and
takes in Bir Tawil. ICPAC's own maps, and the authoritative 205,999-cell domain the model
runs on, do the opposite: Sudan reaches about 23.1 degrees N between 34 and 37 degrees E
(Halaib) and stops short of 22 degrees N between 33.2 and 34.1 degrees E (Bir Tawil). With
the old outline the maps clipped the forecast in Halaib away and drew a straight line
there. This script redraws Sudan as ICPAC does, from Natural Earth's polygons of the two
areas (public domain): ne_10m_admin_0_disputed_areas.geojson from
https://github.com/nvkelso/natural-earth-vector/tree/master/geojson

It also writes frontend/public/icpac-countries.geojson, the same outlines for the
interactive map.

Usage (needs shapely, which the service itself does not):
    python scripts/build_icpac_boundaries.py <ne_10m_admin_0_disputed_areas.geojson>
"""

import json
import sys
from pathlib import Path

from shapely import make_valid, snap
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cartography" / "east_africa_11_adm0.geojson"
OUTPUT = ROOT / "cartography" / "icpac11_adm0.geojson"
FRONTEND = ROOT / "frontend" / "public" / "icpac-countries.geojson"
SNAP = 0.01  # degrees: the two sources' 22 degrees N lines differ by about 0.004
MIN_PART = 0.001  # square degrees: slivers where the sources meet, and islets (as before)


def area(name: str, features: list[dict]) -> Polygon | MultiPolygon:
    found = [f for f in features if f["properties"].get("BRK_NAME") == name]
    if len(found) != 1:
        raise SystemExit(f"Natural Earth file has {len(found)} '{name}' features")
    return make_valid(shape(found[0]["geometry"]))


def tidy(geometry) -> Polygon | MultiPolygon:
    """Drop slivers and pinholes left by the overlay."""
    parts = geometry.geoms if hasattr(geometry, "geoms") else [geometry]
    kept = []
    for part in parts:
        if not isinstance(part, Polygon) or part.area < MIN_PART:
            continue
        holes = [h for h in part.interiors if Polygon(h).area >= MIN_PART]
        kept.append(Polygon(part.exterior, holes))
    return kept[0] if len(kept) == 1 else MultiPolygon(kept)


def rounded(geometry) -> dict:
    data = mapping(geometry)

    def walk(value):
        if isinstance(value, (list, tuple)) and value and isinstance(value[0], (int, float)):
            return [round(float(v), 5) for v in value]
        return [walk(v) for v in value]

    return {"type": data["type"], "coordinates": walk(data["coordinates"])}


def main(disputed_path: Path) -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    disputed = json.loads(disputed_path.read_text(encoding="utf-8"))["features"]
    halaib = area("Halayib Triangle", disputed)
    bir_tawil = area("Bir Tawil", disputed)
    features = []
    for feature in source["features"]:
        name = feature["properties"]["country"]
        geometry = make_valid(shape(feature["geometry"]))
        if name == "Sudan":
            geometry = unary_union([geometry, snap(halaib, geometry, SNAP)])
            geometry = tidy(geometry.difference(snap(bir_tawil, geometry, SNAP)))
        features.append({"name": name, "geometry": rounded(geometry)})
    note = (
        "East Africa 11 countries as ICPAC maps them: the HPC package's outlines with Sudan "
        "including the Halaib triangle and excluding Bir Tawil (Natural Earth disputed "
        "areas). Built by scripts/build_icpac_boundaries.py"
    )
    OUTPUT.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "name": "icpac11_adm0",
                "note": note,
                "crs": source["crs"],
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"country": f["name"]},
                        "geometry": f["geometry"],
                    }
                    for f in features
                ],
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    FRONTEND.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": f["name"]},
                        "geometry": f["geometry"],
                    }
                    for f in features
                ],
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    sudan = shape(next(f["geometry"] for f in features if f["name"] == "Sudan"))
    print(f"Sudan: {sudan.geom_type}, bounds {[round(v, 3) for v in sudan.bounds]}")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} and {FRONTEND.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))
