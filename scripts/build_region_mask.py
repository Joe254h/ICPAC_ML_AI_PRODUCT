"""Build the map mask: the world outside the eleven ICPAC member states.

The interactive maps cover everything outside the region with it, so only the member
states' rainfall shows. Run after changing frontend/public/icpac-countries.geojson:

    python -m scripts.build_region_mask
"""

import json
from pathlib import Path

from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

PUBLIC = Path(__file__).resolve().parents[1] / "frontend" / "public"


def main() -> None:
    countries = json.loads((PUBLIC / "icpac-countries.geojson").read_text(encoding="utf-8"))
    # Snap shared borders together so the union leaves no slivers between countries.
    region = unary_union(
        [shape(f["geometry"]).buffer(0.002, join_style="mitre") for f in countries["features"]]
    )
    region = region.buffer(-0.002, join_style="mitre").simplify(0.003)
    outside = box(-180, -85, 180, 85).difference(region)
    feature = {"type": "Feature", "properties": {}, "geometry": mapping(outside)}
    out = PUBLIC / "icpac-outside.geojson"
    out.write_text(
        json.dumps({"type": "FeatureCollection", "features": [feature]}, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"{out}: {out.stat().st_size / 1e3:.0f} kB, {outside.geom_type}")


if __name__ == "__main__":
    main()
