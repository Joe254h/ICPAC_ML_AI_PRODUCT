"""Maps in the layout of the ICPAC weekly bulletin (templates/icpac_weekly_reference.docx).

The geometry was measured from the reference's 1024 x 1024 px maps (``word/media/image8.png``
for the region, ``imaged.png`` for Somalia) and is reproduced here at twice that size:

* Mercator projection with the same scale on both axes (the latitude spacing of the
  reference ticks grows towards the north as Mercator's does); region frame 21.65-51.61 E,
  11.93 S-23.30 N, 707 x 851 px; Somalia frame 40.78-51.61 E, 1.86 S-12.17 N;
* filled contours on the forecast grid, clipped to the countries, white elsewhere;
  black country outlines, thin grey coastlines (no other borders) and shores of Lakes
  Victoria, Tanganyika and Malawi; on the Somalia map, Somalia's regions;
* outward ticks on the left and bottom only, every 5 degrees (2 for a country), labelled
  "25°E", "20°N", "0°", "10°S"; no grid lines;
* a colour bar of equal boxes with dark separators, labelled at the box boundaries;
* the IGAD seal inside the frame, top right (bottom right on the Somalia map);
* a bold title "Total Rainfall (mm) for 06-13 Oct 2026" centred over the frame.

Helvetica in the reference is drawn with Liberation Sans (metric compatible) when installed.
"""

import io
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from matplotlib import font_manager
from matplotlib import image as mpimg
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path as MplPath

from climate_engine.cartography import icpac_maps
from climate_engine.core import ROOT

REFERENCE_PX = 1024
SCALE = 2  # output pixels per reference pixel
DPI = 100 * SCALE
SEAL = ROOT / "cartography" / "igad_seal.png"
LAYERS = ROOT / "cartography" / "weekly_map_layers.geojson"
FONTS = ["Liberation Sans", "Arial", "Helvetica", "Nimbus Sans", "DejaVu Sans"]
# Font sizes in points at 100 dpi on the 1024 px reference (px x 0.72).
TITLE_PT, TICK_PT, BAR_PT, NOTE_PT, MESSAGE_PT = 21.4, 19.8, 16.0, 7.5, 15.0
TICK_LENGTH_PT, TICK_PAD_PT, LINE_PT = 15.1, 14.4, 0.75
TITLE_BASELINE_PX = 42.0
BAR_LABEL_GAP_PX = 14.0
GREY = "#8c8c8c"


@dataclass(frozen=True)
class Layout:
    """Positions in reference pixels (origin top left) and the map extent in degrees."""

    extent: tuple[float, float, float, float]  # west, east, south, north
    frame: tuple[float, float, float, float]  # left, top, right, bottom
    bar: tuple[float, float, float, float]
    logo: tuple[float, float, float, float]
    tick_step: int


REGION = Layout(
    extent=(21.65, 51.61, -11.93, 23.30),
    frame=(129.5, 88.5, 836.0, 939.0),
    bar=(881.0, 96.0, 923.0, 932.0),
    logo=(719.5, 104.5, 819.5, 204.5),
    tick_step=5,
)
SOMALIA = Layout(
    extent=(40.78, 51.61, -1.86, 12.17),
    frame=(159.5, 87.0, 813.5, 940.0),
    bar=(856.0, 94.0, 894.0, 934.0),
    logo=(699.5, 823.0, 800.5, 924.0),
    tick_step=2,
)
CENTRE_PX = 526.5  # horizontal centre of frame plus colour bar in both references


@dataclass(frozen=True)
class Scale:
    """Discrete classes: ``levels`` are the class edges, one colour per class."""

    levels: tuple[float, ...]
    colors: tuple[str, ...]


# Reference colour classes (sampled from the reference maps' colour bars).
RAINFALL = Scale(
    (0.0, 1.0, 10.0, 30.0, 50.0, 100.0, 200.0, math.inf),
    ("#d8d8d8", "#ffa500", "#ffff00", "#caff70", "#00ff00", "#66cd00", "#228b22"),
)


def mercator(latitude: np.ndarray | float) -> np.ndarray:
    """Mercator northing in degrees: equal scale with longitude at the equator."""
    phi = np.radians(np.clip(np.asarray(latitude, dtype=float), -85.0, 85.0))
    return np.degrees(np.log(np.tan(np.pi / 4 + phi / 2)))


def degree_label(value: float, axis: str) -> str:
    if value == 0:
        return "0°"
    if axis == "x":
        return f"{abs(value):g}°{'E' if value > 0 else 'W'}"
    return f"{abs(value):g}°{'N' if value > 0 else 'S'}"


def country_layout(country: icpac_maps.Country) -> Layout:
    """Somalia uses the reference geometry; other countries follow the same proportions."""
    if country.name == "Somalia":
        return SOMALIA
    west, south, east, north = country.bounds
    pad = 0.2
    west, east, south, north = west - pad, east + pad, south - pad, north + pad
    top, height = 87.0, 853.0
    ratio = (east - west) / float(mercator(north) - mercator(south))
    width = height * ratio
    if width > 700.0:  # wide countries: keep the frame inside the page
        width, height = 700.0, 700.0 / ratio
    gap, bar_width = 44.0, 40.0
    left = CENTRE_PX - (width + gap + bar_width) / 2
    right, bottom = left + width, top + height
    step = 1 if max(east - west, north - south) < 6 else 2
    logo = 101.0
    return Layout(
        extent=(west, east, south, north),
        frame=(left, top, right, bottom),
        bar=(right + gap, top + 7, right + gap + bar_width, bottom - 6),
        logo=(right - 14 - logo, bottom - 16 - logo, right - 14, bottom - 16),
        tick_step=step,
    )


@cache
def seal() -> np.ndarray:
    return mpimg.imread(SEAL)


@cache
def extra_lines(path: Path = LAYERS) -> dict[str, list[np.ndarray]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    lines: dict[str, list[np.ndarray]] = {}
    for feature in data["features"]:
        role = feature["properties"]["role"]
        lines.setdefault(role, []).append(np.asarray(feature["geometry"]["coordinates"]))
    return lines


def projected(rings: Sequence[np.ndarray]) -> list[np.ndarray]:
    return [np.column_stack([ring[:, 0], mercator(ring[:, 1])]) for ring in rings]


def outside_path(rings: list[np.ndarray], extent: tuple[float, float, float, float]) -> MplPath:
    """The frame with the given (projected) rings cut out: clips lines to outside them."""
    west, east, south, north = extent
    south, north = float(mercator(south)), float(mercator(north))
    pad = 1.0
    outer = np.array(
        [
            [west - pad, south - pad],
            [east + pad, south - pad],
            [east + pad, north + pad],
            [west - pad, north + pad],
            [west - pad, south - pad],
        ]
    )
    vertices, codes = [outer], [[MplPath.MOVETO] + [MplPath.LINETO] * 3 + [MplPath.CLOSEPOLY]]
    for ring in rings:
        x, y = ring[:, 0], ring[:, 1]
        signed = float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
        hole = ring if signed < 0 else ring[::-1]  # clockwise inside the counter-clockwise frame
        vertices.append(hole)
        codes.append([MplPath.MOVETO] + [MplPath.LINETO] * (len(hole) - 2) + [MplPath.CLOSEPOLY])
    return MplPath(np.vstack(vertices), np.concatenate(codes))


def inside_path(rings: list[np.ndarray]) -> MplPath:
    vertices, codes = [], []
    for ring in rings:
        vertices.append(ring)
        codes.append([MplPath.MOVETO] + [MplPath.LINETO] * (len(ring) - 2) + [MplPath.CLOSEPOLY])
    return MplPath(np.vstack(vertices), np.concatenate(codes))


def font_family() -> list[str]:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    return [name for name in FONTS if name in installed] or ["DejaVu Sans"]


def _axes_rect(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    left, top, right, bottom = box
    size = REFERENCE_PX
    return (left / size, 1 - bottom / size, (right - left) / size, (bottom - top) / size)


def render(
    title: str,
    field: icpac_maps.Field | None = None,
    scale: Scale = RAINFALL,
    country: str | None = None,
    note: str = "",
    message: str = "",
) -> bytes:
    """A PNG in the reference layout; without a field, ``message`` fills the frame."""
    countries = icpac_maps.load_boundaries(icpac_maps.BOUNDARIES)
    if country is None:
        layout, shown = REGION, countries
    else:
        shown = tuple(c for c in countries if c.name == country)
        if not shown:
            raise ValueError(f"Unknown map country: {country}")
        layout = country_layout(shown[0])
    west, east, south, north = layout.extent
    shown_rings = projected([ring for c in shown for ring in c.rings])
    lines = extra_lines()

    with icpac_maps.standard_style():
        figure = Figure(figsize=(REFERENCE_PX / 100, REFERENCE_PX / 100), dpi=DPI)
        agg = FigureCanvasAgg(figure)
        figure.set_facecolor("white")
        family = font_family()
        ax = figure.add_axes(_axes_rect(layout.frame))
        ax.set_xlim(west, east)
        ax.set_ylim(float(mercator(south)), float(mercator(north)))
        ax.set_aspect("auto")
        ax.set_facecolor("white")

        image = None
        if field is not None:
            values = np.array(field.values, dtype=float)
            lat = np.asarray(field.latitude, dtype=float)
            lon = np.asarray(field.longitude, dtype=float)
            if lat[0] > lat[-1]:
                lat, values = lat[::-1], values[::-1]
            levels = [lvl if math.isfinite(lvl) else 1e12 for lvl in scale.levels]
            image = ax.contourf(
                lon,
                mercator(lat),
                np.ma.masked_invalid(values),
                levels=levels,
                colors=scale.colors,
                zorder=1,
            )
            image.set_clip_path(inside_path(shown_rings), ax.transData)

        clip_outside = outside_path(shown_rings, layout.extent)
        # Coastlines in grey outside the mapped countries (their own outline is black),
        # lake shores in grey over the field, as in the reference.
        coast = LineCollection(
            projected(lines.get("coast", [])), colors=GREY, linewidths=0.6, zorder=2
        )
        ax.add_collection(coast, autolim=False)
        coast.set_clip_path(clip_outside, ax.transData)
        ax.add_collection(
            LineCollection(projected(lines.get("lake", [])), colors=GREY, linewidths=0.6, zorder=3),
            autolim=False,
        )
        if country == "Somalia":
            regions = LineCollection(
                projected(lines.get("admin1", [])), colors="black", linewidths=0.55, zorder=3
            )
            ax.add_collection(regions, autolim=False)
            regions.set_clip_path(inside_path(shown_rings), ax.transData)
        ax.add_collection(
            LineCollection(shown_rings, colors="black", linewidths=LINE_PT, zorder=4),
            autolim=False,
        )

        xticks = np.arange(
            math.ceil(west / layout.tick_step), math.floor(east / layout.tick_step) + 1
        )
        yticks = np.arange(
            math.ceil(south / layout.tick_step), math.floor(north / layout.tick_step) + 1
        )
        ax.set_xticks(xticks * layout.tick_step)
        ax.set_xticklabels([degree_label(float(v * layout.tick_step), "x") for v in xticks])
        ax.set_yticks(mercator(yticks * layout.tick_step))
        ax.set_yticklabels([degree_label(float(v * layout.tick_step), "y") for v in yticks])
        ax.tick_params(
            direction="out",
            length=TICK_LENGTH_PT,
            width=LINE_PT,
            pad=TICK_PAD_PT,
            labelsize=TICK_PT,
            top=False,
            right=False,
        )
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontfamily(family)
        for spine in ax.spines.values():
            spine.set_linewidth(LINE_PT)

        logo = figure.add_axes(_axes_rect(layout.logo), zorder=5)
        logo.imshow(seal())
        logo.set_axis_off()

        frame_left, _, frame_right, _ = layout.frame
        figure.text(
            (frame_left + frame_right) / 2 / REFERENCE_PX,
            1 - TITLE_BASELINE_PX / REFERENCE_PX,
            title,
            ha="center",
            va="baseline",
            fontsize=TITLE_PT,
            fontweight="bold",
            fontfamily=family,
        )
        if image is not None:
            _colour_bar(figure, layout, scale, family)
        if message:
            ax.text(
                0.5,
                0.5,
                message,
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=MESSAGE_PT,
                fontfamily=family,
                color="#444444",
                linespacing=1.5,
                zorder=6,
                bbox={"facecolor": "white", "edgecolor": GREY, "boxstyle": "round,pad=0.8"},
            )
        if note:
            text = figure.text(
                8 / REFERENCE_PX,
                6 / REFERENCE_PX,
                note,
                ha="left",
                va="bottom",
                fontsize=NOTE_PT,
                fontfamily=family,
                color="#555555",
            )
            # Keep the whole label on the page: shrink a long one to the page width.
            width = text.get_window_extent(agg.get_renderer()).width
            available = figure.bbox.width * (1 - 16 / REFERENCE_PX)
            if width > available:
                text.set_fontsize(NOTE_PT * available / width)
        output = io.BytesIO()
        figure.savefig(output, format="png", dpi=DPI, facecolor="white")
    return output.getvalue()


def _colour_bar(figure: Figure, layout: Layout, scale: Scale, family: list[str]) -> None:
    """Equal boxes with dark separators, labelled at the inner class edges."""
    bar = figure.add_axes(_axes_rect(layout.bar))
    count = len(scale.colors)
    for index, colour in enumerate(scale.colors):
        bar.add_patch(
            Rectangle((0, index), 1, 1, facecolor=colour, edgecolor="#222222", linewidth=0.6)
        )
    bar.set_xlim(0, 1)
    bar.set_ylim(0, count)
    bar.set_axis_off()
    bar.add_patch(
        PathPatch(
            MplPath([(0, 0), (1, 0), (1, count), (0, count), (0, 0)]),
            fill=False,
            edgecolor="#666666",
            linewidth=0.6,
        )
    )
    left, top, right, bottom = layout.bar
    for index, level in enumerate(scale.levels[1:-1], start=1):
        y = bottom - (bottom - top) * index / count
        figure.text(
            (right + BAR_LABEL_GAP_PX) / REFERENCE_PX,
            1 - y / REFERENCE_PX,
            f"{level:g}",
            ha="left",
            va="center",
            fontsize=BAR_PT,
            fontfamily=family,
        )
