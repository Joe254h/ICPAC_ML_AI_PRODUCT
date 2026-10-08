"""ICPAC Week-2 map standard: one renderer for forecast and verification maps.

The HPC map driver ``cartography/121b_final_atmospheric_maps_icpac_standard.py`` imports
a frozen module ``icpac_maps`` that was not delivered. This module reconstructs that
standard and keeps the driver's interface (``Field``, ``Style``, ``STYLES``, ``Layer``,
``Figure``, ``Canvas``, ``build``, ``OUTDIR``, ``HDR``, ``BOUNDARIES``, ``LOGO`` and
``FROZEN_EXTENT``). The geometry was measured from the delivered reference maps
(fixtures/references/, saved at 220 dpi) and is checked against them by
backend/tests/test_cartography.py:

* extent: the cartographic boundary bounds plus 1.0 degree on each side
  (references 20.83-52.40 E, -12.72-23.19 N);
* latitude/longitude axes with aspect 1/cos(central latitude), the references'
  y/x pixel-per-degree ratio of 1.0042;
* map frame 1420 px high for a single map and 886.5 px in a panel (at 220 dpi);
* ticks every 5 degrees, labels "Longitude (°E)" and "Latitude (°)", faint grid lines
  drawn over the field;
* the field clipped to the union of the official country polygons (white outside), 0.8 pt
  black country boundaries drawn from the GeoJSON, never derived from the raster mask;
* cells outside the authoritative domain stay white: the references show values in 313
  cells inside the boundaries that the 205,999-cell domain excludes (Bir Tawil and slivers
  along the Sudan-South Sudan border), so they were drawn on an earlier domain;
* a colourbar as tall as the frame with matplotlib's 20:1 aspect, separated from the
  frame by 4.75% of the frame width for a single map and 6.31% in a panel;
* bold 15 pt title "LABEL | Quantity" 10 pt above the frame; 11 pt axis labels; 10 pt ticks;
* the IGAD/ICPAC logo (white background) at axes fraction x 0.828-0.932, y 0.790-0.910;
* matplotlib's default style and DejaVu Sans, whatever the host's matplotlibrc says.

When the frozen ``icpac_maps.py`` is supplied, its values replace these in one place.
"""

import io
import json
import math
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import matplotlib.style
import numpy as np
from matplotlib import colors
from matplotlib import image as mpimg
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure as MplFigure
from matplotlib.path import Path as MplPath
from matplotlib.ticker import FuncFormatter
from matplotlib.transforms import Bbox

from climate_engine.core import ROOT
from climate_engine.operational.grid import DomainGrid, load_grid

BOUNDARIES = ROOT / "cartography" / "east_africa_11_adm0.geojson"
LOGO = ROOT / "cartography" / "IGAD-CPAC-01.jpg"
DOMAIN_MASK = ROOT / "artifacts" / "domain" / "authoritative_icpac11_mask.npz"

# Set by the HPC driver: output directory for build() and a header line for its figures.
OUTDIR: Path | None = None
HDR = ""

DPI = 220
EXTENT_PADDING_DEG = 1.0
TICK_SPACING_DEG = 5
FRAME_HEIGHT_IN = {"single": 1420 / DPI, "panel": 886.5 / DPI}
COLORBAR_GAP = {"single": 0.0475, "panel": 0.0631}  # fraction of the frame width
COLORBAR_ASPECT = 20  # long to short side
LOGO_BOX = (0.8279, 0.7901, 0.1043, 0.1197)  # axes fraction: x0, y0, width, height
TITLE_SIZE, TITLE_PAD, LABEL_SIZE = 15, 10, 11
HEADER_SIZE, NOTE_SIZE = 15, 10
PANEL_SPACING_IN = 0.1
BOUNDARY_COLOR, BOUNDARY_WIDTH = "black", 0.8
GRID_STYLE = {"color": "#b0b0b0", "linewidth": 0.4, "alpha": 0.12}
STYLE_RC = {"font.family": "DejaVu Sans", "savefig.dpi": DPI}

_LOCK = threading.RLock()  # rcParams are global: one rendering at a time


@dataclass(frozen=True)
class Style:
    cmap: str
    label: str
    kind: str  # "continuous" or "diverging"
    vmin: float | None = None
    vmax: float | None = None
    extend: str = "neither"
    provisional: bool = False  # not confirmed by a reference map or the HPC driver
    levels: tuple[float, ...] | None = None
    palette: tuple[str, ...] | None = None
    geographic_ticks: bool = False


STYLES: dict[str, Style] = {
    # Measured from the reference maps.
    "rmse": Style("YlOrRd", "RMSE (mm/week)", "continuous", vmin=0.0),
    "correlation": Style("viridis", "Pearson r", "continuous"),
    "improvement": Style("RdBu", "Relative RMSE improvement", "diverging"),
    # Defined by the 121b driver.
    "delta_rmse_atmos": Style(
        "RdBu_r", "Atmospheric37 − Final Hybrid7 RMSE (mm/week)", "diverging", -1.0, 1.0, "both"
    ),
    "gain_final7": Style(
        "RdBu", "RMSE improvement vs Final Hybrid7 (%)", "diverging", -10.0, 10.0, "both"
    ),
    "delta_corr_atmos": Style(
        "RdBu", "Change in Pearson correlation", "diverging", -0.10, 0.10, "both"
    ),
    "fraction_better": Style("RdBu", "Fraction of 537 cases", "continuous", 0.25, 0.75),
    "delta_abs_bias": Style(
        "RdBu_r", "Change in absolute bias (mm/week)", "diverging", -1.0, 1.0, "both"
    ),
    # Not shown by any reference: provisional until the frozen styles are supplied.
    "mae": Style("YlOrRd", "MAE (mm/week)", "continuous", vmin=0.0, provisional=True),
    "bias": Style("BrBG", "Bias: forecast − CHIRPS (mm/week)", "diverging", provisional=True),
    "rainfall": Style(
        "YlGnBu",
        "Total rainfall (mm/week)",
        "discrete",
        0.0,
        500.0,
        levels=(0.0, 1.0, 10.0, 30.0, 50.0, 100.0, 200.0, 500.0),
        palette=("#d9d9d9", "#ffa500", "#ffff00", "#caff70", "#00ff00", "#66cd00", "#228b22"),
        geographic_ticks=True,
    ),
    "residual": Style(
        "BrBG", "CatBoost residual: CHIRPS − MBC (mm/week)", "diverging", provisional=True
    ),
}


@dataclass
class Field:
    """A field on a regular latitude/longitude grid (NaN where there is no value)."""

    name: str
    values: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray


@dataclass
class Layer:
    """One map: its title, its field (or a loader returning it) and a style key."""

    title: str
    source: Field | Callable[[], Field]
    style: str
    limits: tuple[float, float] | None = None

    def field(self) -> Field:
        return self.source() if callable(self.source) else self.source


@dataclass
class Figure:
    """A product: one map or a panel of maps (saved as <name>.png by build)."""

    name: str
    layers: list[Layer]
    title: str = ""  # figure title above a panel; single maps carry only the map title
    ncols: int = 1
    note: str = ""  # one line under the maps (initialisation, validity, model status)


@dataclass
class Country:
    name: str
    rings: list[np.ndarray] = field(default_factory=list)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        points = np.vstack(self.rings)
        return (
            float(points[:, 0].min()),
            float(points[:, 1].min()),
            float(points[:, 0].max()),
            float(points[:, 1].max()),
        )


@cache
def load_boundaries(path: Path = BOUNDARIES) -> tuple[Country, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    countries = []
    for feature in data["features"]:
        geometry = feature["geometry"]
        polygons = (
            [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        )
        rings = [np.asarray(ring, dtype=float)[:, :2] for polygon in polygons for ring in polygon]
        countries.append(Country(feature["properties"]["country"], rings))
    return tuple(countries)


def union_path(countries: tuple[Country, ...]) -> MplPath:
    """A compound path of every boundary ring, used to clip the field."""
    vertices, codes = [], []
    for country in countries:
        for ring in country.rings:
            vertices.append(ring)
            codes.append(
                [MplPath.MOVETO] + [MplPath.LINETO] * (len(ring) - 2) + [MplPath.CLOSEPOLY]
            )
    return MplPath(np.vstack(vertices), np.concatenate(codes))


def frozen_extent(countries: tuple[Country, ...]) -> tuple[float, float, float, float]:
    """(west, east, south, north): boundary bounds plus the 1-degree frame."""
    points = np.vstack([ring for c in countries for ring in c.rings])
    pad = EXTENT_PADDING_DEG
    return (
        float(points[:, 0].min() - pad),
        float(points[:, 0].max() + pad),
        float(points[:, 1].min() - pad),
        float(points[:, 1].max() + pad),
    )


def __getattr__(name: str) -> Any:
    if name == "FROZEN_EXTENT":
        return frozen_extent(load_boundaries(BOUNDARIES))
    raise AttributeError(name)


@cache
def logo_image(path: Path = LOGO) -> np.ndarray:
    return mpimg.imread(path)


@cache
def valid_mask(path: Path = DOMAIN_MASK) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The authoritative domain mask with its ascending latitude and longitude."""
    grid = load_grid(path)
    return grid.mask, grid.latitude, grid.longitude


def limits(values: np.ndarray, style: Style) -> tuple[float, float]:
    """Colour limits: fixed where the style fixes them, otherwise robust data limits."""
    if style.vmin is not None and style.vmax is not None:
        return style.vmin, style.vmax
    finite = values[np.isfinite(values)]
    if style.kind == "diverging":
        bound = float(np.percentile(np.abs(finite), 98)) if finite.size else 1.0
        return -(bound or 1.0), bound or 1.0
    low = (
        style.vmin
        if style.vmin is not None
        else (float(np.percentile(finite, 2)) if finite.size else 0.0)
    )
    high = (
        style.vmax
        if style.vmax is not None
        else (float(np.percentile(finite, 98)) if finite.size else 1.0)
    )
    return (low, high) if high > low else (low, low + 1.0)


@contextmanager
def standard_style() -> Iterator[None]:
    """matplotlib's default style with the map font, independent of the host's rc files."""
    with _LOCK, matplotlib.style.context(["default", STYLE_RC]):
        yield


class Canvas:
    """Geometry shared by every map: extent, aspect, boundaries, clip path and logo."""

    def __init__(
        self,
        use_valid_mask: bool = True,
        boundaries: Path = BOUNDARIES,
        logo: Path = LOGO,
        mask: Path | DomainGrid = DOMAIN_MASK,
        country: str | None = None,
    ):
        self.countries = load_boundaries(boundaries)
        if country is not None:
            self.countries = tuple(c for c in self.countries if c.name == country)
            if not self.countries:
                raise ValueError(f"Unknown map country: {country}")
        self.extent = frozen_extent(self.countries)
        self.logo_box = LOGO_BOX
        self.tick_spacing = TICK_SPACING_DEG
        if country is not None:
            west, south, east, north = self.countries[0].bounds
            self.extent = (west - 0.25, east + 0.25, south - 0.25, north + 0.25)
            self.logo_box = (0.82, 0.02, 0.15, 0.12)  # offshore, as in the Somalia reference
            self.tick_spacing = 2
        self.clip = union_path(self.countries)
        self.logo = logo_image(logo)
        self.valid: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        if use_valid_mask:
            self.valid = (
                (mask.mask, mask.latitude, mask.longitude)
                if isinstance(mask, DomainGrid)
                else valid_mask(mask)
            )
        west, east, south, north = self.extent
        self.aspect = 1.0 / math.cos(math.radians((south + north) / 2))
        self.height_per_width = (north - south) * self.aspect / (east - west)

    def prepare(self, data: Field) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Values with ascending latitude, restricted to the domain mask when enabled."""
        values = np.array(data.values, dtype=float)
        lat = np.asarray(data.latitude, dtype=float)
        lon = np.asarray(data.longitude, dtype=float)
        if values.shape != (lat.size, lon.size):
            raise ValueError(f"{data.name}: values {values.shape} do not match the coordinates")
        if lat[0] > lat[-1]:
            lat, values = lat[::-1], values[::-1]
        if self.valid is not None:
            mask, mask_lat, mask_lon = self.valid
            if (
                mask.shape != values.shape
                or not np.allclose(lat, mask_lat, atol=1e-4)
                or not np.allclose(lon, mask_lon, atol=1e-4)
            ):
                raise ValueError(
                    f"{data.name}: the validity mask applies to fields on the authoritative "
                    "grid; use Canvas(use_valid_mask=False) for other grids"
                )
            values[~mask] = np.nan
        return values, lat, lon

    def draw(
        self,
        ax: Any,
        cax: Any,
        layer: Layer,
        prepared: tuple[np.ndarray, np.ndarray, np.ndarray],
        bounds: tuple[float, float],
    ) -> Any:
        style = STYLES[layer.style]
        values, lat, lon = prepared
        west, east, south, north = self.extent
        dy = abs(lat[1] - lat[0]) / 2 if lat.size > 1 else 0.025
        dx = abs(lon[1] - lon[0]) / 2 if lon.size > 1 else 0.025
        vmin, vmax = bounds
        cmap = colors.ListedColormap(style.palette) if style.palette else style.cmap
        norm = (
            colors.BoundaryNorm(style.levels, len(style.palette))
            if style.levels and style.palette
            else (
                colors.TwoSlopeNorm(vcenter=0.0, vmin=vmin, vmax=vmax)
                if style.kind == "diverging" and vmin < 0 < vmax
                else colors.Normalize(vmin=vmin, vmax=vmax)
            )
        )
        image = ax.imshow(
            np.ma.masked_invalid(values),
            origin="lower",
            extent=(lon[0] - dx, lon[-1] + dx, lat[0] - dy, lat[-1] + dy),
            cmap=cmap,
            norm=norm,
            interpolation="nearest",
        )
        image.set_clip_path(self.clip, ax.transData)
        ax.add_collection(
            LineCollection(
                [ring for c in self.countries for ring in c.rings],
                colors=BOUNDARY_COLOR,
                linewidths=BOUNDARY_WIDTH,
                zorder=3,
            ),
            autolim=False,
        )
        ax.set_xlim(west, east)
        ax.set_ylim(south, north)
        ax.set_aspect(self.aspect)
        step = self.tick_spacing
        ax.set_xticks(np.arange(math.ceil(west / step), math.floor(east / step) + 1) * step)
        ax.set_yticks(np.arange(math.ceil(south / step), math.floor(north / step) + 1) * step)
        ax.set_xlabel("Longitude (°E)", fontsize=LABEL_SIZE)
        ax.set_ylabel("Latitude (°)", fontsize=LABEL_SIZE)
        if style.geographic_ticks:
            ax.xaxis.set_major_formatter(
                FuncFormatter(lambda v, _: f"{abs(v):g}°{'E' if v >= 0 else 'W'}")
            )
            ax.yaxis.set_major_formatter(
                FuncFormatter(
                    lambda v, _: "0°" if v == 0 else f"{abs(v):g}°{'N' if v > 0 else 'S'}"
                )
            )
            ax.set_xlabel("")
            ax.set_ylabel("")
        ax.grid(True, **GRID_STYLE)
        ax.set_title(layer.title, fontsize=TITLE_SIZE, fontweight="bold", pad=TITLE_PAD)
        bar = ax.figure.colorbar(image, cax=cax, extend=style.extend)
        bar.set_label(style.label)
        if style.levels:
            bar.set_ticks(style.levels[1:-1])
        logo = ax.inset_axes(self.logo_box, zorder=5)
        logo.imshow(self.logo)
        logo.set_axis_off()
        return image


def shared_limits(
    layers: list[Layer], prepared: list[tuple[np.ndarray, np.ndarray, np.ndarray]]
) -> list[tuple[float, float]]:
    """Layers with the same style share one colour scale, so they can be compared."""
    pooled: dict[str, list[np.ndarray]] = {}
    for layer, (values, _, _) in zip(layers, prepared, strict=True):
        if layer.limits is None:
            pooled.setdefault(layer.style, []).append(values.ravel())
    scales = {
        style: limits(np.concatenate(chunks), STYLES[style]) for style, chunks in pooled.items()
    }
    return [layer.limits or scales[layer.style] for layer in layers]


def _extents(fig: MplFigure, ax: Any, cax: Any, renderer: Any) -> tuple[float, ...]:
    """Inches that decorations reach beyond the frame: left, right, top, bottom."""
    frame = ax.get_window_extent(renderer)
    tight = Bbox.union([ax.get_tightbbox(renderer), cax.get_tightbbox(renderer)])
    return (
        (frame.x0 - tight.x0) / fig.dpi,
        (tight.x1 - frame.x1) / fig.dpi,
        (tight.y1 - frame.y1) / fig.dpi,
        (frame.y0 - tight.y0) / fig.dpi,
    )


def render(spec: Figure, canvas: Canvas | None = None) -> MplFigure:
    """Lay out one map or a panel with fixed frame sizes (in inches) and tight spacing."""
    if not spec.layers:
        raise ValueError(f"{spec.name}: a figure needs at least one layer")
    unknown = sorted({layer.style for layer in spec.layers} - set(STYLES))
    if unknown:
        raise ValueError(f"{spec.name}: unknown map styles {unknown}")
    canvas = canvas or Canvas()
    with standard_style():
        prepared = [canvas.prepare(layer.field()) for layer in spec.layers]
        scales = shared_limits(spec.layers, prepared)
        layout = "single" if len(spec.layers) == 1 else "panel"
        frame_h = FRAME_HEIGHT_IN[layout]
        frame_w = frame_h / canvas.height_per_width
        gap, bar_w = COLORBAR_GAP[layout] * frame_w, frame_h / COLORBAR_ASPECT
        ncols = max(1, min(spec.ncols, len(spec.layers)))
        nrows = math.ceil(len(spec.layers) / ncols)

        fig = MplFigure(figsize=(ncols * (frame_w + 4), nrows * (frame_h + 3)), dpi=DPI)
        fig.set_facecolor("white")
        agg = FigureCanvasAgg(fig)
        panels = []
        for index, (layer, data, bounds) in enumerate(
            zip(spec.layers, prepared, scales, strict=True)
        ):
            row, col = divmod(index, ncols)
            x, y = 2 + col * (frame_w + 4), 1.5 + row * (frame_h + 3)
            ax = fig.add_axes(_rect(fig, x, y, frame_w, frame_h))
            cax = fig.add_axes(_rect(fig, x + frame_w + gap, y, bar_w, frame_h))
            canvas.draw(ax, cax, layer, data, bounds)
            panels.append((row, col, ax, cax))
        header = [
            fig.text(0.5, 0.99, text, ha="center", va="top", fontsize=size, fontweight=weight)
            for text, size, weight in (
                (spec.title, HEADER_SIZE, "bold"),
                (HDR, NOTE_SIZE + 1, "normal"),
            )
            if text
        ]
        note = (
            fig.text(
                0.01, 0.01, spec.note, ha="left", va="bottom", fontsize=NOTE_SIZE, color="#333333"
            )
            if spec.note
            else None
        )

        # Text extents in inches do not depend on the figure size: measure once, then
        # place every frame at its fixed size with the decorations packed around it.
        renderer = agg.get_renderer()
        extents = {(r, c): _extents(fig, ax, cax, renderer) for r, c, ax, cax in panels}
        left = [max(e[0] for (_, c), e in extents.items() if c == j) for j in range(ncols)]
        right = [max(e[1] for (_, c), e in extents.items() if c == j) for j in range(ncols)]
        top = [max(e[2] for (r, _), e in extents.items() if r == i) for i in range(nrows)]
        bottom = [max(e[3] for (r, _), e in extents.items() if r == i) for i in range(nrows)]
        lines = [t.get_window_extent(renderer).height / DPI + 0.08 for t in header]
        note_h = note.get_window_extent(renderer).height / DPI + 0.15 if note else 0.0
        col_x = np.cumsum(
            [0.0] + [left[j] + frame_w + right[j] + PANEL_SPACING_IN for j in range(ncols)]
        )
        row_y = np.cumsum(
            [sum(lines)] + [top[i] + frame_h + bottom[i] + PANEL_SPACING_IN for i in range(nrows)]
        )
        width = float(col_x[-1] - PANEL_SPACING_IN)
        height = float(row_y[-1] - PANEL_SPACING_IN + note_h)
        fig.set_size_inches(width, height)
        for row, col, ax, cax in panels:
            x, y = col_x[col] + left[col], row_y[row] + top[row]
            ax.set_position(_rect(fig, x, y, frame_w, frame_h))
            cax.set_position(_rect(fig, x + frame_w + gap, y, bar_w, frame_h))
        for text, offset in zip(header, np.cumsum([0.0] + lines)[:-1], strict=True):
            text.set_position((0.5, 1 - offset / height))
        if note is not None:
            note.set_position((0.0, 0.0))
    return fig


def _rect(
    fig: MplFigure, x: float, y: float, w: float, h: float
) -> tuple[float, float, float, float]:
    """Figure-fraction rectangle from inches measured from the top-left corner."""
    fw, fh = fig.get_size_inches()
    return (x / fw, 1 - (y + h) / fh, w / fw, h / fh)


def to_png(fig: MplFigure) -> bytes:
    buffer = io.BytesIO()
    with standard_style():
        fig.savefig(
            buffer, format="png", dpi=DPI, bbox_inches="tight", pad_inches=0.1, facecolor="white"
        )
    return buffer.getvalue()


def render_png(spec: Figure, canvas: Canvas | None = None) -> bytes:
    with standard_style():
        return to_png(render(spec, canvas))


def build(canvas: Canvas, spec: Figure, outdir: Path | None = None) -> Path:
    """Render a figure to <outdir or OUTDIR>/<name>.png (the HPC driver's entry point)."""
    directory = outdir or OUTDIR
    if directory is None:
        raise ValueError("Set icpac_maps.OUTDIR or pass outdir")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{spec.name}.png"
    path.write_bytes(render_png(spec, canvas))
    return path
