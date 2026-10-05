import json
from functools import lru_cache

import numpy as np
from matplotlib.path import Path

from climate_engine.core import ROOT, config


@lru_cache
def boundaries() -> dict:
    return json.loads((ROOT / config()["country_mask"]).read_text(encoding="utf-8"))


def country_mask(country: str, latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray:
    xx, yy = np.meshgrid(longitude, latitude)
    points = np.column_stack([xx.ravel(), yy.ravel()])
    selected = np.zeros(len(points), dtype=bool)
    for feature in boundaries()["features"]:
        if feature["properties"]["name"] != country:
            continue
        geom = feature["geometry"]
        polygons = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for polygon in polygons:
            inside = Path(polygon[0]).contains_points(points)
            for hole in polygon[1:]:
                inside &= ~Path(hole).contains_points(points)
            selected |= inside
    return selected.reshape(xx.shape)


def weighted_mean(values: np.ndarray, latitude: np.ndarray, mask: np.ndarray) -> float | None:
    weights = np.broadcast_to(np.cos(np.deg2rad(latitude))[:, None], values.shape)
    valid = mask & np.isfinite(values)
    return float(np.average(values[valid], weights=weights[valid])) if valid.any() else None
