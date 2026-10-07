"""Structural visual regression of the ICPAC map standard against the delivered references.

The references (fixtures/references/) and the platform's renderings are measured by the
same code (map_geometry): frames, extent, aspect, colourbars, logo and boundary lines
must agree to within a few pixels. Pixel values are not compared: the references were
drawn from HPC verification fields that are not part of the package.
"""

from pathlib import Path

import matplotlib
import numpy as np
import pytest
from matplotlib import image as mpimg
from scipy import ndimage
from scipy.spatial import cKDTree

from backend.tests.map_geometry import boundary_points, load, measure
from climate_engine.cartography import icpac_maps as maps
from climate_engine.core import ROOT
from climate_engine.operational.grid import load_grid

REFERENCES = ROOT / "fixtures" / "references"
SINGLE = {
    "rmse": ("hybrid_RMSE_FINAL.png", "HYBRID | Week-2 Rainfall RMSE"),
    "correlation": ("hybrid_Correlation_FINAL.png", "HYBRID | Temporal Correlation"),
}
PANEL = "PANEL_RMSE_RAW_HYBRID_CATBOOST.png"


def smooth(lat: np.ndarray, lon: np.ndarray, scale: float = 1.0) -> np.ndarray:
    lon2, lat2 = np.meshgrid(lon, lat)
    return scale * (18 + 12 * np.sin(np.radians(lon2 * 7)) * np.cos(np.radians(lat2 * 9)))


@pytest.fixture(scope="module")
def grid():
    return maps.valid_mask()


@pytest.fixture(scope="module")
def renders(tmp_path_factory, grid) -> dict[str, Path]:
    _, lat, lon = grid
    out = tmp_path_factory.mktemp("maps")
    rmse = smooth(lat, lon)
    corr = 0.6 + 0.3 * np.sin(np.radians(np.add.outer(lat * 4, lon * 5)))
    specs = {
        "rmse": maps.Figure(
            "rmse", [maps.Layer(SINGLE["rmse"][1], maps.Field("rmse", rmse, lat, lon), "rmse")]
        ),
        "correlation": maps.Figure(
            "correlation",
            [maps.Layer(SINGLE["correlation"][1], maps.Field("r", corr, lat, lon), "correlation")],
        ),
        "panel": maps.Figure(
            "panel",
            [
                maps.Layer(
                    "RAW ECMWF | Week-2 Rainfall RMSE",
                    maps.Field("raw", rmse * 1.1, lat, lon),
                    "rmse",
                ),
                maps.Layer(
                    "HYBRID | Week-2 Rainfall RMSE", maps.Field("h", rmse, lat, lon), "rmse"
                ),
                maps.Layer(
                    "CATBOOST | Week-2 Rainfall RMSE",
                    maps.Field("c", rmse * 0.95, lat, lon),
                    "rmse",
                ),
                maps.Layer(
                    "MBC + CatBoost | RMSE Improvement Relative to Raw ECMWF",
                    maps.Field("i", corr - 0.6, lat, lon),
                    "improvement",
                ),
            ],
            ncols=2,
        ),
    }
    return {name: maps.build(maps.Canvas(), spec, out) for name, spec in specs.items()}


def close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= tolerance


@pytest.mark.parametrize("name", sorted(SINGLE))
def test_single_map_geometry_matches_the_reference(renders, name):
    reference_path = REFERENCES / SINGLE[name][0]
    [reference], [ours] = measure(reference_path), measure(renders[name])
    ref_size = load(reference_path).shape[:2]
    our_size = load(renders[name]).shape[:2]
    assert all(close(a, b, 0.01 * a) for a, b in zip(ref_size, our_size, strict=True))
    r, o = reference.frame, ours.frame
    for attr in ("left", "top", "width", "height"):
        assert close(getattr(r, attr), getattr(o, attr), 3), attr
    assert all(close(a, b, 0.05) for a, b in zip(reference.extent, ours.extent, strict=True))
    for frame in (reference, ours):  # latitude axis stretched by 1/cos(central latitude)
        assert close(frame.px_per_deg[1] / frame.px_per_deg[0], 1.0042, 0.002)
    rc, oc = reference.colourbar, ours.colourbar
    assert rc is not None and oc is not None
    assert close(oc.top, o.top, 1) and close(oc.bottom, o.bottom, 1)
    assert close(oc.left - o.right, rc.left - r.right, 2) and close(oc.width, rc.width, 2)
    assert reference.logo is not None and ours.logo is not None
    for attr in ("left", "right", "top", "bottom"):
        assert close(getattr(reference.logo, attr), getattr(ours.logo, attr), 0.01), attr


def test_panel_geometry_matches_the_reference(renders):
    reference, ours = measure(REFERENCES / PANEL), measure(renders["panel"])
    assert len(reference) == len(ours) == 4
    for frames in (reference, ours):  # a 2 x 2 grid of aligned frames
        assert close(frames[0].frame.top, frames[1].frame.top, 1)
        assert close(frames[2].frame.top, frames[3].frame.top, 1)
        assert close(frames[0].frame.left, frames[2].frame.left, 1)
        assert close(frames[1].frame.left, frames[3].frame.left, 1)
    for r, o in zip(reference, ours, strict=True):
        assert close(r.frame.width, o.frame.width, 3) and close(r.frame.height, o.frame.height, 3)
        assert all(close(a, b, 0.07) for a, b in zip(r.extent, o.extent, strict=True))
        assert r.colourbar is not None and o.colourbar is not None
        assert close(o.colourbar.left - o.frame.right, r.colourbar.left - r.frame.right, 2)
        assert close(o.colourbar.width, r.colourbar.width, 2)
        assert close(o.colourbar.height, o.frame.height, 1)
        assert r.logo is not None and o.logo is not None
        assert close(r.logo.left, o.logo.left, 0.01) and close(r.logo.top, o.logo.top, 0.01)
    pitch = ours[1].frame.left - ours[0].frame.left, ours[2].frame.top - ours[0].frame.top
    ref_pitch = (
        reference[1].frame.left - reference[0].frame.left,
        reference[2].frame.top - reference[0].frame.top,
    )
    assert all(close(a, b, 0.05 * b) for a, b in zip(pitch, ref_pitch, strict=True))


@pytest.mark.parametrize("name", ["rmse", "correlation", "panel"])
def test_boundaries_overlay_the_reference_boundaries(renders, name):
    reference_path = REFERENCES / (SINGLE[name][0] if name in SINGLE else PANEL)
    for ref_frame, our_frame in zip(measure(reference_path), measure(renders[name]), strict=True):
        ref_points = boundary_points(reference_path, ref_frame)
        our_points = boundary_points(renders[name], our_frame)
        ours_to_ref = cKDTree(ref_points).query(our_points)[0]
        ref_to_ours = cKDTree(our_points).query(ref_points)[0]
        for distances in (ours_to_ref, ref_to_ours):  # degrees; one pixel is 0.025-0.04
            assert np.median(distances) < 0.015 and np.percentile(distances, 95) < 0.05
        assert close(len(our_points), len(ref_points), 0.10 * len(ref_points)), "line width"


def draw(fig) -> np.ndarray:
    with maps.standard_style():
        fig.canvas.draw()
        return np.asarray(fig.canvas.buffer_rgba())[..., :3] / 255.0


def test_field_is_clipped_to_the_official_boundaries(grid):
    """Nothing outside the country union, and every domain cell inside it, is coloured."""
    mask, lat, lon = grid
    canvas = maps.Canvas()
    full = np.full(mask.shape, 25.0)  # values on every cell of the 800 x 700 grid
    spec = maps.Figure("clip", [maps.Layer("TEST | Clip", maps.Field("c", full, lat, lon), "rmse")])
    fig = maps.render(spec, canvas)
    rgb = draw(fig)
    ax = fig.axes[0]
    x0, y0, x1, y1 = ax.get_window_extent().extents
    height = rgb.shape[0]
    cols, rows = np.meshgrid(  # every other pixel: 0.05 degrees per sample
        np.arange(int(x0) + 3, int(x1) - 2, 2), np.arange(int(y0) + 3, int(y1) - 2, 2)
    )
    lon_px, lat_px = (
        ax.transData.inverted()
        .transform(np.column_stack([cols.ravel() + 0.5, rows.ravel() + 0.5]))
        .T
    )
    inside = canvas.clip.contains_points(np.column_stack([lon_px, lat_px])).reshape(cols.shape)
    pixels = rgb[height - 1 - rows, cols]
    white = pixels.min(axis=2) > 0.93  # grid lines leave white at 0.96
    fx = (cols - x0) / (x1 - x0)
    fy = (rows - y0) / (y1 - y0)
    bx, by, bw, bh = maps.LOGO_BOX
    logo = (fx > bx - 0.01) & (fx < bx + bw + 0.01) & (fy > by - 0.01) & (fy < by + bh + 0.01)
    outside = ndimage.binary_erosion(~inside, iterations=2) & ~logo
    i = np.clip(np.round((lat_px - lat[0]) / 0.05).astype(int), 0, lat.size - 1)
    j = np.clip(np.round((lon_px - lon[0]) / 0.05).astype(int), 0, lon.size - 1)
    in_domain = mask[i, j].reshape(cols.shape)
    covered = ndimage.binary_erosion(inside & in_domain, iterations=2)
    assert outside.sum() > 50_000 and covered.sum() > 50_000
    assert white[outside].mean() > 0.999, "field drawn outside the boundaries"
    assert (~white[covered]).mean() > 0.999, "domain cells missing inside the boundaries"
    # The 667 domain cells north of the Sudan boundary (up to 23.125 N) are clipped away.
    north = outside & (lat_px.reshape(cols.shape) > 22.3) & (lat_px.reshape(cols.shape) < 23.1)
    north &= (lon_px.reshape(cols.shape) > 34.2) & (lon_px.reshape(cols.shape) < 36.5)
    assert north.sum() > 300 and white[north].all()


def test_somalia_and_all_eleven_countries_are_drawn(renders, grid):
    countries = maps.load_boundaries()
    names = {country.name for country in countries}
    assert names == set(load_grid(maps.DOMAIN_MASK).country_names) and len(countries) == 11
    west, east, south, north = maps.FROZEN_EXTENT
    for country in countries:  # every country at least 1 degree inside the frame
        x0, y0, x1, y1 = country.bounds
        margins = (x0 - west, east - x1, y0 - south, north - y1)
        assert min(margins) >= 1.0 - 1e-6, country.name
    somalia = next(c for c in countries if c.name == "Somalia")
    assert somalia.bounds[2] > 51.3 and somalia.bounds[3] > 11.9  # Ras Hafun and Cape Guardafui
    [frame] = measure(renders["rmse"])
    rgb = load(renders["rmse"])
    for country in countries:
        vertices = np.vstack(country.rings)[::5]
        x = frame.frame.left + (vertices[:, 0] - frame.extent[0]) * frame.px_per_deg[0]
        y = frame.frame.top + (frame.extent[3] - vertices[:, 1]) * frame.px_per_deg[1]
        hits = [
            (rgb[int(b) - 2 : int(b) + 3, int(a) - 2 : int(a) + 3].max(axis=2) < 0.3).any()
            for a, b in zip(x, y, strict=True)
        ]
        assert np.mean(hits) > 0.97, f"{country.name} boundary not drawn"


def test_titles_labels_and_ticks_follow_the_standard(grid):
    _, lat, lon = grid
    spec = maps.Figure(
        "labels",
        [
            maps.Layer(
                "HYBRID | Week-2 Rainfall RMSE", maps.Field("r", smooth(lat, lon), lat, lon), "rmse"
            )
        ],
    )
    fig = maps.render(spec)
    ax, cax = fig.axes[0], fig.axes[1]
    assert ax.get_title() == "HYBRID | Week-2 Rainfall RMSE"
    assert ax.title.get_fontsize() == 15 and ax.title.get_fontweight() == "bold"
    assert ax.title.get_fontname() == "DejaVu Sans"
    assert ax.get_xlabel() == "Longitude (°E)" and ax.get_ylabel() == "Latitude (°)"
    assert list(ax.get_xticks()) == [25, 30, 35, 40, 45, 50]
    assert list(ax.get_yticks()) == [-10, -5, 0, 5, 10, 15, 20]
    assert cax.get_ylabel() == "RMSE (mm/week)"
    assert cax.get_ylim()[0] == 0.0  # RMSE scale starts at zero


def test_rendering_ignores_the_host_matplotlib_configuration(grid, monkeypatch):
    _, lat, lon = grid
    monkeypatch.setitem(matplotlib.rcParams, "font.family", ["serif"])
    monkeypatch.setitem(matplotlib.rcParams, "axes.titlesize", 30)
    spec = maps.Figure(
        "rc", [maps.Layer("HYBRID | Test", maps.Field("r", smooth(lat, lon), lat, lon), "rmse")]
    )
    fig = maps.render(spec)
    assert fig.axes[0].title.get_fontname() == "DejaVu Sans"
    assert fig.axes[0].title.get_fontsize() == 15
    assert fig.axes[0].xaxis.label.get_fontname() == "DejaVu Sans"
    assert matplotlib.rcParams["font.family"] == ["serif"]  # restored afterwards


def coarse() -> tuple[np.ndarray, np.ndarray]:
    return np.arange(-12.5, 23.6, 0.5), np.arange(21.0, 52.6, 0.5)


def test_layers_with_one_style_share_a_colour_scale():
    lat, lon = coarse()
    raw, mbc, hybrid = (smooth(lat, lon, s) for s in (1.4, 1.1, 1.0))
    spec = maps.Figure(
        "shared",
        [
            maps.Layer("RAW ECMWF | Week-2 Rainfall", maps.Field("raw", raw, lat, lon), "rainfall"),
            maps.Layer("MBC | Week-2 Rainfall", maps.Field("mbc", mbc, lat, lon), "rainfall"),
            maps.Layer("HYBRID | Week-2 Rainfall", maps.Field("h", hybrid, lat, lon), "rainfall"),
            maps.Layer("HYBRID | Residual", maps.Field("res", hybrid - mbc, lat, lon), "residual"),
            maps.Layer("FIXED | Scale", maps.Field("f", hybrid, lat, lon), "rmse", (0.0, 50.0)),
        ],
        ncols=3,
    )
    fig = maps.render(spec, maps.Canvas(use_valid_mask=False))
    scales = [ax.images[0].get_clim() for ax in fig.axes if ax.images]
    assert len(scales) == 5
    assert scales[0] == scales[1] == scales[2]
    assert scales[0][0] == 0.0 and scales[0][1] > float(np.percentile(hybrid, 98))
    assert scales[3][0] == -scales[3][1]  # diverging scales are symmetric about zero
    assert scales[4] == (0.0, 50.0)


def test_hpc_driver_interface(tmp_path, monkeypatch):
    """The 121b driver's calls work unchanged: Field, Style, Layer, Figure, Canvas, build."""
    lat, lon = coarse()
    monkeypatch.setattr(maps, "OUTDIR", tmp_path / "final_scientific_maps")
    monkeypatch.setattr(maps, "HDR", "Week-2 (days 8–14) | test header")
    monkeypatch.setitem(
        maps.STYLES,
        "delta_test",
        maps.Style("RdBu_r", "Delta (mm/week)", "diverging", vmin=-1.0, vmax=1.0, extend="both"),
    )
    spec = maps.Figure(
        "01_TEST_ICPAC",
        [
            maps.Layer(
                "Final Hybrid7", lambda: maps.Field("a", smooth(lat, lon), lat, lon), "rmse"
            ),
            maps.Layer(
                "Atmospheric37 − Final Hybrid7\nBlue = improvement",
                lambda: maps.Field("b", smooth(lat, lon) / 20 - 1, lat, lon),
                "delta_test",
            ),
        ],
        "Week-2 Rainfall RMSE: Final Hybrid7 vs Atmospheric Hybrid37",
        ncols=2,
    )
    output = maps.build(maps.Canvas(use_valid_mask=False), spec)
    assert output == tmp_path / "final_scientific_maps" / "01_TEST_ICPAC.png"
    image = mpimg.imread(output)
    assert image.shape[0] > 500 and image.shape[1] > 1000
    assert len(measure(output)) == 2
    fig = maps.render(spec, maps.Canvas(use_valid_mask=False))
    texts = [t.get_text() for t in fig.texts]
    assert spec.title in texts and maps.HDR in texts
    assert maps.FROZEN_EXTENT == maps.frozen_extent(maps.load_boundaries())


@pytest.mark.parametrize(
    "problem, message",
    [
        ("style", "unknown map styles"),
        ("shape", "do not match the coordinates"),
        ("grid", "authoritative grid"),
        ("empty", "at least one layer"),
    ],
)
def test_invalid_map_requests_fail_clearly(problem, message):
    lat, lon = coarse()
    values = smooth(lat, lon)
    layer = maps.Layer("X | Y", maps.Field("x", values, lat, lon), "rmse")
    if problem == "style":
        layer.style = "not_a_style"
    if problem == "shape":
        layer.source = maps.Field("x", values[:-1], lat, lon)
    spec = maps.Figure("bad", [] if problem == "empty" else [layer])
    with pytest.raises(ValueError, match=message):
        maps.render(spec, maps.Canvas(use_valid_mask=problem == "grid"))
