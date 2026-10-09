"""End-to-end on the committed HPC artifacts and the full 800 x 700 grid.

1. The operational path through the API: an ECMWF Open Data download (from a local mirror
   holding real GRIB2 files), Week-2 processing, interpolation to the model grid, MBC, the
   205,999-cell domain, country mapping, the bulletin-style maps and the API the frontend
   reads. The AI/ML layer is in progress until its pressure-level inputs are supplied.
2. The full hybrid chain (Atmos37 features, the 378-tree CatBoost residual, max(MBC +
   residual, 0)) on a labelled synthetic fixture with test pressure steps, outside the API.
"""

import json
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
from backend.tests import ecmwf_mirror
from backend.tests.map_geometry import measure
from climate_engine.cartography import icpac_maps, weekly_maps
from climate_engine.core import ROOT
from climate_engine.forecasts import ECMWFS2SForecastProvider
from climate_engine.forecasts.fixtures import FIXTURE_PRESSURE_STEPS_HOURS, write_fixture
from climate_engine.models.descriptor import load_descriptor
from climate_engine.operational.grid import load_grid
from climate_engine.operational.pipeline import run_forecast
from climate_engine.operational.settings import settings

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
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("FORECAST_INPUT_ROOT", str(tmp_path / "inputs"))
    root = tmp_path / "mirror"
    ecmwf_mirror.build(root, date(2026, 10, 5))
    operational.authoritative_grid.cache_clear()
    operational._models.clear()
    with ecmwf_mirror.serve(root) as url:
        monkeypatch.setenv("ECMWF_OPENDATA_MIRRORS", url)
        with TestClient(create_app(f"sqlite:///{tmp_path / 'db.sqlite'}")) as c:
            yield c


def test_open_data_forecast_runs_end_to_end_through_the_api(client, tmp_path):
    current = client.get("/models/current").json()
    assert current["role"] == "candidate"
    assert current["model"]["model_id"] == "mbc_atmos37_catboost_candidate_v1"

    response = client.post(
        "/forecasts/run",
        json={"initialization": "2026-10-05", "source": "ecmwf_opendata", "actor": "E2E"},
    )
    assert response.status_code == 201, response.text
    fid = response.json()["forecast_id"]
    detail = client.get(f"/forecasts/{fid}").json()
    provenance = detail["provenance"]
    assert provenance["model_id"] == "mbc_atmos37_catboost_candidate_v1"
    assert provenance["model"]["family"] == "MBC" and provenance["primary_layer"] == "mbc"
    assert provenance["products"]["hybrid"]["status"] == "in_progress"
    assert provenance["input_label"] == "ECMWF ENS (Open Data)"
    assert provenance["grid_definition"]["shape"] == [800, 700]
    assert provenance["domain_definition"]["cells"] == 205_999
    assert provenance["mbc_month"] == 10 and provenance["doy_date"] == "2026-10-05"
    assert provenance["forecast_valid_start"] == "2026-10-12T00:00:00+00:00"
    assert provenance["ensemble_members"] == 3 and provenance["protected_test_period"] is False
    assert detail["model_status"] == "candidate" and detail["synthetic"] is False
    assert detail["layers"] == ["mbc", "raw"]

    netcdf = client.get(f"/forecasts/{fid}/package/forecast.nc").content
    path = tmp_path / "forecast.nc"
    path.write_bytes(netcdf)
    with xr.open_dataset(path) as stored:
        data = stored.load()
    grid = load_grid(MASK)
    assert set(data.data_vars) == {"raw", "mbc", "domain_mask"}
    fields = {name: data[name].values.astype(np.float64) for name in ("raw", "mbc")}
    for values in fields.values():
        assert np.isfinite(values[grid.mask]).sum() == 205_999
        assert np.isnan(values[~grid.mask]).all()
    assert (fields["raw"][grid.mask] > 0).all()
    with np.load(MBC) as mbc:
        ratio = mbc["ratio"][9]  # October: the initialization month
    np.testing.assert_allclose(
        fields["mbc"][grid.mask], np.maximum(0, fields["raw"][grid.mask] * ratio), rtol=1e-5
    )

    countries = client.get(f"/forecasts/{fid}/countries").json()
    assert {c["country"]: c["cell_count"] for c in countries} == COUNTRY_CELLS
    for row in countries:
        assert 0 <= row["mbc"]["min_mm"] <= row["mbc"]["mean_mm"] <= row["mbc"]["max_mm"]

    # Rainfall maps (served and packaged) follow the ICPAC weekly bulletin's layout.
    for url in (f"/forecasts/{fid}/map?layer=mbc", f"/forecasts/{fid}/package/maps/mbc.png"):
        (tmp_path / "mbc.png").write_bytes(client.get(url).content)
        [frame] = measure(tmp_path / "mbc.png")
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
        pixels = np.asarray(Image.open(tmp_path / "mbc.png").convert("RGB"))
        bar_left, bar_top, bar_right, bar_bottom = (
            int(v * weekly_maps.SCALE) for v in weekly_maps.REGION.bar
        )
        column = pixels[bar_top:bar_bottom, (bar_left + bar_right) // 2]
        colours = list(dict.fromkeys("#%02x%02x%02x" % tuple(p) for p in column[::-1]))
        assert [c for c in colours if c in weekly_maps.RAINFALL.colors] == list(
            weekly_maps.RAINFALL.colors
        ), url
    assert client.get(f"/forecasts/{fid}/map?layer=hybrid").status_code == 404
    health = client.get("/health").json()["components"]
    assert health["Operational forecasts"] == "Healthy · latest from the ECMWF run of 5 Oct 2026"
    assert health["ECMWF input"] == "Healthy · latest run 5 Oct 2026, 00 UTC"


def test_the_hybrid_chain_runs_on_the_real_artifacts(tmp_path):
    """MBC + 378-tree CatBoost residual on the full grid, with test pressure steps."""
    cfg = settings()
    cfg["ecmwf"]["pressure"]["week2_steps_hours"] = list(FIXTURE_PRESSURE_STEPS_HOURS)
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
    descriptor = load_descriptor("config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml")
    fields, model = descriptor.verified(grid, cfg)
    record = {**fields, "status": "candidate"}
    provider = ECMWFS2SForecastProvider(rainfall, pressure, cfg)
    run = run_forecast(provider, "2026-10-05", model, grid, cfg, record)
    p = run.provenance
    assert p["model"]["trees"] == 378 and p["model"]["family"] == "atmos37"
    assert p["primary_layer"] == "hybrid" and p["synthetic"] is True
    data = run.dataset
    values = {
        n: data[n].values.astype(np.float64)[grid.mask] for n in ("mbc", "residual", "hybrid")
    }
    assert all(np.isfinite(v).all() for v in values.values())
    assert (values["hybrid"] >= 0).all()
    np.testing.assert_allclose(
        values["hybrid"], np.maximum(values["mbc"] + values["residual"], 0), atol=1e-4
    )
    # The residual keeps the HPC driver's verification-map standard.
    from climate_engine.products.package import map_figures

    png = icpac_maps.render_png(map_figures(run, record)["residual"], icpac_maps.Canvas(mask=grid))
    (tmp_path / "residual.png").write_bytes(png)
    [frame] = measure(tmp_path / "residual.png")
    assert abs(frame.frame.height - 1420) <= 3 and abs(frame.frame.width - 1243) <= 3
    assert np.allclose(frame.extent, (20.83, 52.40, -12.72, 23.19), atol=0.06)
    assert frame.colourbar is not None and frame.logo is not None


def test_without_pressure_steps_the_hpc_command_publishes_raw_and_mbc(tmp_path):
    """The HPC command never guesses the seven Week-2 pressure steps: it publishes raw ECMWF
    and MBC and records the hybrid as in progress."""
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
        timeout=600,
    )
    assert result.returncode == 0, result.stderr
    [package] = list((tmp_path / "packages").iterdir())
    provenance = json.loads((package / "provenance.json").read_text())
    assert provenance["layers"] == ["raw", "mbc"]
    assert "forecast hours" in provenance["products"]["hybrid"]["reason"]
    assert not (package / "maps" / "hybrid.png").exists()
