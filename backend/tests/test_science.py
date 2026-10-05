import numpy as np
import pytest

from climate_engine.forecasts import MockForecastProvider
from climate_engine.models import ArtifactModel, MockForecastModel
from climate_engine.observations import LocalNetCDFProvider, MockObservationProvider
from climate_engine.preprocessing import accumulate_week2, align_exact
from climate_engine.qc import check_dataset, check_file
from climate_engine.verification import metrics


@pytest.mark.parametrize("source", ["CHIRPS", "TAMSAT", "RFE2"])
def test_observation_schema_dates_metadata(source):
    p = MockObservationProvider(source)
    ds = p.load("2026-09-22", "2026-09-28")
    assert ds.sizes == {"time": 7, "latitude": 60, "longitude": 60}
    assert ds.attrs["source"] == source
    assert check_dataset(ds, "2026-09-22", "2026-09-28")["status"] == "PASS"
    with pytest.raises(ValueError):
        p.load("2020-01-01", "2020-01-02")
    with pytest.raises(ValueError):
        p.load("2026-09-22", "2026-09-28", "temperature")


def test_forecast_window_and_missing_lead():
    ds = MockForecastProvider().load("2026-09-21")
    np.testing.assert_allclose(
        accumulate_week2(ds), ds.precipitation.isel(time=slice(7, 14)).sum("time")
    )
    with pytest.raises(ValueError):
        accumulate_week2(ds.isel(time=slice(0, 13)))


def test_qc_blocks_bad_inputs(tmp_path):
    ds = MockForecastProvider().load("2026-09-21")
    assert check_dataset(ds, forecast=True)["status"] == "PASS"
    invalid = ds.copy(deep=True)
    invalid.precipitation.values[:, :, :] = np.nan
    assert check_dataset(invalid)["status"] == "FAIL"
    assert check_dataset(ds.assign_coords(time=[ds.time.values[0]] * 14))["status"] == "FAIL"
    assert check_dataset(ds.drop_vars("latitude"))["status"] == "FAIL"
    assert check_dataset(ds.drop_vars("precipitation"))["status"] == "FAIL"
    invalid = ds.copy(deep=True)
    invalid.attrs["units"] = "m"
    assert check_dataset(invalid)["status"] == "FAIL"
    invalid.precipitation.values[0, 0, 0] = np.inf
    assert check_dataset(invalid)["status"] == "FAIL"
    file = tmp_path / "corrupt.nc"
    file.write_text("not NetCDF")
    assert check_file(str(file))["status"] == "FAIL"
    assert check_file(str(tmp_path / "missing.nc"))["status"] == "FAIL"


def test_missing_values_not_summed_as_zero():
    ds = MockForecastProvider().load("2026-09-21")
    ds.precipitation.values[8, 0, 0] = np.nan
    assert np.isnan(accumulate_week2(ds).values[0, 0])


def test_model_contract_and_alignment(tmp_path):
    raw = accumulate_week2(MockForecastProvider().load("2026-09-21"))
    np.testing.assert_allclose(MockForecastModel().predict(raw), raw * 0.83 + 1.2)
    with pytest.raises(ValueError):
        MockForecastModel().predict(raw.assign_attrs(feature_schema="hybrid7"))
    with pytest.raises(FileNotFoundError):
        ArtifactModel("catboost", str(tmp_path / "absent.cbm"), "rainfall_total_v1").load()
    with pytest.raises(ValueError):
        align_exact(raw, raw.assign_coords(longitude=raw.longitude + 0.1))


def test_known_metrics_and_constant_arrays():
    score = metrics(np.array([2.0, 4.0, 6.0]), np.array([1.0, 2.0, 3.0]))
    assert score["mae"] == 2
    assert score["bias"] == 2
    assert score["rmse"] == pytest.approx(np.sqrt(14 / 3))
    assert score["correlation"] == pytest.approx(1)
    assert metrics(np.ones(3), np.ones(3))["correlation"] is None
    with pytest.raises(ValueError):
        metrics(np.array([np.nan]), np.array([1]))
    with pytest.raises(ValueError):
        metrics(np.ones(2), np.ones(3))


def test_local_ingestion_missing_file_and_units(tmp_path):
    with pytest.raises(FileNotFoundError):
        LocalNetCDFProvider("CHIRPS", str(tmp_path / "absent.nc")).load("2026-09-01", "2026-09-02")
    ds = MockObservationProvider("CHIRPS").load("2026-09-22", "2026-09-28")
    ds.attrs["units"] = "m"
    path = tmp_path / "units.nc"
    ds.to_netcdf(path, engine="scipy")
    with pytest.raises(ValueError, match="conversion"):
        LocalNetCDFProvider("CHIRPS", str(path)).load("2026-09-22", "2026-09-28")
