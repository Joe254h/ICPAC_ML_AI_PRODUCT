"""Forecast fields as transparent map overlays for web maps (MapLibre, Leaflet).

Web maps draw in Web Mercator, so the overlay is resampled from the regular latitude grid
to Mercator rows; drawn on its bounds it then sits exactly on the basemap. Colours are the
ICPAC weekly bulletin's rainfall classes; cells outside the domain are transparent.
"""

import io

import numpy as np

from climate_engine.cartography.weekly_maps import RAINFALL, Scale


def _mercator(latitude: np.ndarray) -> np.ndarray:
    phi = np.radians(np.clip(latitude, -85.0, 85.0))
    return np.log(np.tan(np.pi / 4 + phi / 2))


def _latitude(y: np.ndarray) -> np.ndarray:
    return np.degrees(2 * np.arctan(np.exp(y)) - np.pi / 2)


def bounds(latitude: np.ndarray, longitude: np.ndarray) -> list[float]:
    """[west, south, east, north] of the grid's cell edges."""
    dlat = float(np.median(np.diff(latitude)))
    dlon = float(np.median(np.diff(longitude)))
    return [
        round(float(longitude[0]) - dlon / 2, 6),
        round(float(latitude[0]) - dlat / 2, 6),
        round(float(longitude[-1]) + dlon / 2, 6),
        round(float(latitude[-1]) + dlat / 2, 6),
    ]


def rgba(values: np.ndarray, scale: Scale = RAINFALL, opacity: float = 0.85) -> np.ndarray:
    """Class colours for each value; missing values are fully transparent."""
    colours = np.array(
        [[int(c[i : i + 2], 16) for i in (1, 3, 5)] for c in scale.colors], dtype=np.uint8
    )
    edges = np.asarray(scale.levels[1:-1], dtype=float)
    finite = np.isfinite(values)
    classes = np.digitize(np.where(finite, values, 0.0), edges)
    out = np.zeros((*values.shape, 4), dtype=np.uint8)
    out[..., :3] = colours[classes]
    alpha = np.where(classes == 0, 0.45, opacity)  # the "below 1 mm" class stays light
    out[..., 3] = np.where(finite, np.round(alpha * 255), 0).astype(np.uint8)
    return out


def mercator_png(
    values: np.ndarray, latitude: np.ndarray, longitude: np.ndarray, scale: Scale = RAINFALL
) -> bytes:
    """The field (latitude ascending, longitude ascending) as a north-up Mercator PNG."""
    from PIL import Image

    west, south, east, north = bounds(latitude, longitude)
    top, bottom = _mercator(np.array([north, south]))
    width = longitude.size
    height = int(round(width * (top - bottom) / np.radians(east - west)))
    rows = _latitude(top - (np.arange(height) + 0.5) * (top - bottom) / height)
    dlat = (north - south) / latitude.size
    source = np.clip(((rows - south) / dlat).astype(int), 0, latitude.size - 1)
    image = rgba(values[source, :], scale)
    buffer = io.BytesIO()
    Image.fromarray(image, "RGBA").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
