"""End-to-end: synthetic ECMWF S2S input -> real candidate model -> API response.

One complete chain with the committed HPC artifacts on the full 800 x 700 grid: Week-2
processing, grid alignment, MBC, Atmos37 features, the 378-tree CatBoost residual,
max(MBC + residual, 0), the 205,999-cell domain, country mapping, ICPAC map rendering and
the API that the frontend reads. The input is a labelled synthetic fixture, so no HPC data
or ECMWF archive is needed.
"""

import subprocess
import sys
from datetime import date

import numpy as np
import pytest
import xarray as xr
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from backend.app.services import operational
from backend.tests.map_geometry import measure
from climate_engine.cartography import weekly_maps
from climate_engine.core import ROOT
from climate_engine.forecasts.fixtures import FIXTURE_PRESSURE_STEPS_HOURS, write_fixture
from climate_engine.operational.grid import load_grid

COUNTRY_CELLS = {
    "Kenya": 19249,
    "Ethiopia": 37069,
    "Uganda": 7836,
    "Tanzania": 30817,
    "Somalia": 20945,
    "Sudan": 63284,
    "South Sudan": 20250,
    "Eritrea": 4126,
    "Djibouti": 721,
    "Rwanda": 817,
    "Burundi": 885,
}
MASK = ROOT / "artifacts" / "domain" / "authoritative_icpac11_mask.npz"
MBC = ROOT / "artifacts" / "mbc" / "final_mbc_params_2005_2021_full_corrected_domain.npz"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("ARTIFACT_ROOT", raising=False)
    monkeypatch.setenv("AUTO_REGISTER_MODELS", "true")
    monkeypatch.setenv("ALLOW_SYNTHETIC_FORECASTS", "true")
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    operational.authoritative_grid.cache_clear()
    operational._models.clear()
    with TestClient(create_app(f"sqlite:///{tmp_path / 'db.sqlite'}")) as c:
        yield c


def test_synthetic_forecast_runs_end_to_end_through_the_api(client, tmp_path):
    current = client.get("/models/current").json()
    assert current["role"] == "candidate"
    assert current["model"]["model_id"] == "mbc_atmos37_catboost_candidate_v1"

    response = client.post(
        "/forecasts/run",
        json={"initialization": "2026-10-05", "source": "synthetic_fixture", "actor": "E2E"},
    )
    assert response.status_code == 201, response.text
    fid = response.json()["forecast_id"]
    detail = client.get(f"/forecasts/{fid}").json()
    provenance = detail["provenance"]
    assert provenance["model_id"] == "mbc_atmos37_catboost_candidate_v1"
    assert provenance["model"]["trees"] == 378 and provenance["model"]["family"] == "atmos37"
    assert provenance["grid_definition"]["shape"] == [800, 700]
    assert provenance["domain_definition"]["cells"] == 205_999
    assert provenance["mbc_month"] == 10 and provenance["doy_date"] == "2026-10-05"
    assert provenance["forecast_valid_start"] == "2026-10-12T00:00:00+00:00"
    assert provenance["ensemble_members"] == 4 and provenance["protected_test_period"] is False
    assert detail["model_status"] == "candidate" and detail["synthetic"] is True
    assert "SYNTHETIC TEST INPUT: not a forecast of real weather" in detail["manifest"]["labels"]

    netcdf = client.get(f"/forecasts/{fid}/package/forecast.nc").content
    path = tmp_path / "forecast.nc"
    path.write_bytes(netcdf)
    with xr.open_dataset(path) as stored:
        data = stored.load()
    grid = load_grid(MASK)
    assert data["hybrid"].shape == (800, 700)
    fields = {name: data[name].values.astype(np.float64) for name in ("raw", "mbc", "hybrid")}
    residual = data["residual"].values.astype(np.float64)
    for values in (*fields.values(), residual):
        assert np.isfinite(values[grid.mask]).sum() == 205_999
        assert np.isnan(values[~grid.mask]).all()
    hybrid = fields["hybrid"][grid.mask]
    assert (hybrid >= 0).all()
    np.testing.assert_allclose(
        hybrid, np.maximum(fields["mbc"][grid.mask] + residual[grid.mask], 0), atol=1e-4
    )
    with np.load(MBC) as mbc:
        ratio = mbc["ratio"][9]  # October: the initialization month
    np.testing.assert_allclose(
        fields["mbc"][grid.mask], np.maximum(0, fields["raw"][grid.mask] * ratio), rtol=1e-5
    )

    countries = client.get(f"/forecasts/{fid}/countries").json()
    assert {c["country"]: c["cell_count"] for c in countries} == COUNTRY_CELLS
    for row in countries:
        assert 0 <= row["hybrid"]["min_mm"] <= row["hybrid"]["mean_mm"] <= row["hybrid"]["max_mm"]

    # Rainfall maps (served and packaged) follow the ICPAC weekly bulletin's layout.
    for url in (f"/forecasts/{fid}/map?layer=hybrid", f"/forecasts/{fid}/package/maps/hybrid.png"):
        (tmp_path / "hybrid.png").write_bytes(client.get(url).content)
        [frame] = measure(tmp_path / "hybrid.png")
        left, top, right, bottom = (v * weekly_maps.SCALE for v in weekly_maps.REGION.frame)
        box = frame.frame
        assert (
            max(
                abs(box.left - left),
                abs(box.top - top),
                abs(box.right - right),
                abs(box.bottom - bottom),
            )
            <= 3
        ), url
        # The colour bar's boxes carry the reference's seven rainfall classes, in order.
        pixels = np.asarray(Image.open(tmp_path / "hybrid.png").convert("RGB"))
        bar_left, bar_top, bar_right, bar_bottom = (
            int(v * weekly_maps.SCALE) for v in weekly_maps.REGION.bar
        )
        column = pixels[bar_top:bar_bottom, (bar_left + bar_right) // 2]
        colours = list(dict.fromkeys("#%02x%02x%02x" % tuple(p) for p in column[::-1]))
        assert [c for c in colours if c in weekly_maps.RAINFALL.colors] == list(
            weekly_maps.RAINFALL.colors
        ), url
    # The residual keeps the HPC driver's verification-map standard.
    png = client.get(f"/forecasts/{fid}/map?layer=residual").content
    (tmp_path / "residual.png").write_bytes(png)
    [frame] = measure(tmp_path / "residual.png")
    assert abs(frame.frame.height - 1420) <= 3 and abs(frame.frame.width - 1243) <= 3
    assert np.allclose(frame.extent, (20.83, 52.40, -12.72, 23.19), atol=0.06)
    assert frame.colourbar is not None and frame.logo is not None
    health = client.get("/health").json()["components"]
    assert health["Operational forecasts"] == "Warning · only synthetic demonstration runs"


def test_real_atmos37_runs_stop_at_the_missing_pressure_steps(tmp_path):
    """The HPC command refuses to guess the seven Week-2 pressure steps."""
    grid = load_grid(MASK)
    rainfall, pressure = write_fixture(
        tmp_path,
        date(2026, 10, 5),
        grid.latitude,
        grid.longitude,
        FIXTURE_PRESSURE_STEPS_HOURS,
        members=2,
        rainfall_steps_hours=(168, 336),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_operational",
            "--init-date",
            "2026-10-05",
            "--descriptor",
            "config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml",
            "--rainfall",
            str(rainfall),
            "--pressure",
            str(pressure),
            "--output",
            str(tmp_path / "packages"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode != 0
    assert "ecmwf.pressure.week2_steps_hours" in result.stderr
    assert not (tmp_path / "packages").exists() or not any((tmp_path / "packages").iterdir())
    assert result.stdout == ""
