"""ICPAC branding for web pages: the IGAD seal as icpac.net shows it on its green header
(white line art with the amber Horn of Africa), derived from cartography/igad_seal.png."""

import base64
import io
from functools import lru_cache

import numpy as np

from climate_engine.core import ROOT

SEAL = ROOT / "cartography" / "igad_seal.png"
AMBER = (245, 179, 53)


@lru_cache(maxsize=1)
def white_seal_png() -> bytes:
    """The seal in white on a transparent background; the Horn of Africa stays amber."""
    from PIL import Image

    rgb = np.asarray(Image.open(SEAL).convert("RGB"), dtype=np.float64)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # Ink is anything darker than the white paper; its strength becomes the alpha.
    ink = np.clip((255.0 * 3 - (r + g + b)) / (255.0 * 3 - 240.0), 0.0, 1.0)
    amber = (r > 180) & (g > 120) & (b < 140) & (r - b > 90)
    out = np.zeros((*rgb.shape[:2], 4), dtype=np.uint8)
    out[..., :3] = 255
    out[amber, :3] = AMBER
    alpha = np.where(amber, 1.0, ink)
    out[..., 3] = np.round(255 * np.clip(alpha * 1.15, 0, 1)).astype(np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(out, "RGBA").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()
