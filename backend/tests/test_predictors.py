"""The HPC predictor kit (training/predictors): catalogue, physics, filters, reduction and
request building, on synthetic data (no network, no GRIB files)."""

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

KIT = Path(__file__).resolve().parents[2] / "training" / "predictors"
sys.path.insert(0, str(KIT))

import common  # noqa: E402
import derive  # noqa: E402
import download  # noqa: E402
import reduce  # noqa: E402


def test_the_catalogue_holds_124_variables_14_fields_in_19_groups():
    cat = common.catalogue()
    assert len(cat["groups"]) == 19
    assert common.count_variables(cat) == 124
    assert len(cat["fields"]) == 14
    ids = []
    for group in cat["groups"].values():
        for var in group.get("variables", []):
            ids += var["id"] if isinstance(var["id"], list) else [var["id"]]
    assert sorted(ids) == list(range(1, 125))
    used = {f for g in cat["groups"].values() for f in g.get("fields", [])}
    assert used == {f["name"] for f in cat["fields"].values()}


def test_the_local_box_is_the_existing_pipelines_27_by_24_grid():
    box = common.Box.of(common.catalogue()["domain"]["local_box"])
    assert box.latitudes().size == 27 and box.longitudes().size == 24


# ---------------------------------------------------------------- physics

LAT = np.linspace(10, -10, 21)
LON = np.linspace(30, 50, 21)


def test_divergence_vorticity_and_convergence_on_the_sphere():
    u = np.full((21, 21), 10.0)
    v = np.zeros((21, 21))
    assert np.abs(derive.divergence(u, v, LAT, LON)).max() < 1e-9
    # A uniform westerly on a sphere has relative vorticity u*tan(latitude)/a.
    expected = 10.0 * np.tan(np.radians(LAT))[:, None] / derive.EARTH_RADIUS
    # (interior rows: the edges use one-sided differences)
    assert np.allclose(
        derive.vorticity(u, v, LAT, LON)[1:-1], expected[1:-1], rtol=1e-3, atol=1e-12
    )
    # Winds blowing in towards 40 E: convergence, so the moisture-flux convergence is > 0.
    inward = -np.sign(LON - 40)[None, :] * np.ones((21, 21)) * 5.0
    q = np.full((21, 21), 0.01)
    mfc = derive.moisture_flux_convergence(
        {925: (q, inward, v), 850: (q, inward, v), 700: (q, inward, v)}, LAT, LON
    )
    assert mfc[10, 10] > 0


def test_humidity_dewpoint_and_k_index_are_physical():
    t = np.array([293.15])
    q_saturated = (
        0.622 * derive.saturation_pressure(t) / (85000 - 0.378 * derive.saturation_pressure(t))
    )
    assert derive.relative_humidity(q_saturated, t, 850)[0] == pytest.approx(100, abs=0.5)
    assert derive.dewpoint(q_saturated, 850)[0] == pytest.approx(293.15, abs=0.3)
    # A moist, unstable tropical column has a K-index in the 30s.
    k = derive.k_index(
        np.array([293.0]),
        np.array([283.0]),
        np.array([267.0]),
        np.array([0.015]),
        np.array([0.008]),
    )
    assert 25 < k[0] < 45


def test_box_extreme_and_rain_weighted_latitude():
    field = np.zeros((21, 21))
    field[15, 5] = 9.0  # at -5 N, 35 E
    value, la, lo = derive.box_extreme(field, LAT, LON, -10, 0, 30, 40, "max")
    assert (value, la, lo) == (9.0, -5.0, 35.0)
    rain = np.zeros((21, 21))
    rain[3, :] = 10.0  # all the rain at 7 N
    assert derive.rain_weighted_latitude(rain, LAT, LON, -10, 10, 30, 50) == pytest.approx(7.0)


def test_kelvin_and_rossby_filters_keep_their_own_waves():
    days, lons = 365, 144
    t = np.arange(days)[:, None, None]
    x = np.arange(lons)[None, None, :] / lons
    kelvin = np.cos(2 * np.pi * (5 * x - t / 7.0))  # eastward, wavenumber 5, 7-day period
    rossby = np.cos(2 * np.pi * (-4 * x - t / 25.0))  # westward, wavenumber 4, 25 days
    data = np.broadcast_to(kelvin + rossby, (days, 3, lons)).copy()
    k = derive.wave_filter(data, "kelvin")
    r = derive.wave_filter(data, "rossby")
    middle = slice(100, 260)  # away from the padded end
    corr_kk = np.corrcoef(k[middle].ravel(), np.broadcast_to(kelvin, data.shape)[middle].ravel())[
        0, 1
    ]
    corr_rr = np.corrcoef(r[middle].ravel(), np.broadcast_to(rossby, data.shape)[middle].ravel())[
        0, 1
    ]
    assert corr_kk > 0.9 and corr_rr > 0.9


# ---------------------------------------------------------------- reduction


def test_the_seasonal_cycle_is_removed_with_training_years_only():
    days = np.tile(np.arange(1, 366, 7), 10).astype(float)
    signal = 5 + 3 * np.cos(2 * np.pi * days / 365.25)
    values = np.column_stack([signal, 2 * signal])
    train = np.arange(days.size) < days.size // 2
    clim = reduce.Climatology.fit(values, days, train, 3)
    assert np.abs(clim.remove(values, days)).max() < 1e-8
    values[0, 1] = np.nan  # a gap is fitted around, not fatal
    assert np.isfinite(reduce.Climatology.fit(values, days, train, 3).coef).all()


def test_modes_are_cut_by_variance_and_never_inside_a_north_pair():
    eig = np.array([10.0, 5.0, 4.9, 1.0, 0.5])
    # 90% needs 3 modes; mode 2 and 3 are inseparable at n=50, so the cut stays after 3.
    assert reduce.choose_modes(eig, 0.9, 10, 50) == 3
    # 70% would stop at 2, inside the pair: moved up to 1.
    assert reduce.choose_modes(eig, 0.7, 10, 50) == 1
    assert reduce.choose_modes(eig, 0.7, 10, 50, north=False) == 2
    assert reduce.north_separated(np.array([10.0, 2.0]), 1000).all()


def test_pca_scores_have_unit_variance_and_round_trip_through_a_file(tmp_path):
    rng = np.random.default_rng(0)
    rows = rng.normal(size=(400, 2)) @ np.array([[3.0, 1.0, 0.0], [0.0, 1.0, 2.0]])
    rows = rows + rng.normal(scale=0.01, size=(400, 3))
    pca = reduce.PCA.fit(rows, 0.95, 5, 400)
    assert pca.kept == 2
    scores = pca.transform(rows)
    assert np.allclose(scores.std(axis=0, ddof=1), 1, atol=1e-6)
    np.savez(tmp_path / "m.npz", **pca.arrays(""))
    again = reduce.PCA.load(np.load(tmp_path / "m.npz"))
    assert np.allclose(again.transform(rows), scores)


def _derived(folder: Path, n_cases: int = 160):
    """A small derived/ folder: 2 local variables per L-group, the fields of two EOF groups,
    SST and indices, with seasonal cycles and noise."""
    import pandas as pd
    import xarray as xr

    rng = np.random.default_rng(1)
    start = date(2005, 1, 3)
    hdates = [start + timedelta(days=60 * i) for i in range(n_cases)]  # 2005-2031
    keys = [f"20250101_{d:%Y%m%d}" for d in hdates]
    doy = np.array([d.timetuple().tm_yday for d in hdates], dtype=float)
    cycle = np.cos(2 * np.pi * doy / 365.25)[:, None, None]
    lat_l, lon_l = np.linspace(25.5, -13.5, 27), np.linspace(18, 52.5, 24)
    common_mode = rng.normal(size=(n_cases, 1, 1))
    local = {}
    for name in ("q850_mean", "q850_spread", "t850_mean", "u850_mean", "sp_mean", "msl_mean"):
        local[name] = (
            ("case", "lat_local", "lon_local"),
            (cycle + common_mode + 0.3 * rng.normal(size=(n_cases, 27, 24))).astype(np.float32),
        )
    xr.Dataset(local, coords={"case": keys, "lat_local": lat_l, "lon_local": lon_l}).to_netcdf(
        folder / "local.nc"
    )
    xr.Dataset(
        {
            "rain_mean": (
                ("case", "lat_local", "lon_local"),
                rng.gamma(2, 5, size=(n_cases, 27, 24)).astype(np.float32),
            )
        },
        coords={"case": keys, "lat_local": lat_l, "lon_local": lon_l},
    ).to_netcdf(folder / "cell.nc")
    lat, lon = np.arange(45, -45.1, -1.5), np.arange(-20, 180.1, 1.5)
    pattern = np.cos(np.radians(lon))[None, :] * np.exp(-((lat / 15) ** 2))[:, None]
    amp = rng.normal(size=(n_cases, 1, 1))
    fields = {
        f: (
            ("case", "lat", "lon"),
            (amp * pattern + 0.1 * rng.normal(size=(n_cases, lat.size, lon.size))).astype(
                np.float32
            ),
        )
        for f in ("u850", "u200", "msl", "olr", "chi200")
    }
    xr.Dataset(fields, coords={"case": keys, "lat": lat, "lon": lon}).to_netcdf(
        folder / "fields.nc"
    )
    slat, slon = np.arange(-29.5, 30, 1.0), np.arange(0.5, 360, 1.0)
    sst = 27 + cycle + rng.normal(size=(n_cases, slat.size, slon.size))
    sst[:, :, 20:40] = np.nan  # land
    xr.Dataset(
        {"sst": (("case", "lat", "lon"), sst.astype(np.float32))},
        coords={"case": keys, "lat": slat, "lon": slon},
    ).to_netcdf(folder / "sst.nc")
    table = pd.DataFrame(
        {
            "hdate": [d.isoformat() for d in hdates],
            "mascarene_pressure": 102000 + 300 * cycle[:, 0, 0] + rng.normal(size=n_cases),
            "rmm1": rng.normal(size=n_cases),
            "nino34": rng.normal(size=n_cases),
            "turkana_jet": 8 + rng.normal(size=n_cases),
        },
        index=pd.Index(keys, name="case"),
    )
    table.to_csv(folder / "indices.csv")
    return keys


def test_fit_then_apply_gives_the_same_features(tmp_path):
    import pandas as pd
    import xarray as xr

    derived = tmp_path / "derived"
    derived.mkdir()
    keys = _derived(derived)
    cat = common.catalogue()
    out, models = tmp_path / "reduced", tmp_path / "reduced" / "models"
    reduce.run(derived, out, models, True, cat)
    summary = __import__("json").loads((models / "summary.json").read_text())
    assert summary["training_cases"] == sum(1 for k in keys if int(k[9:13]) <= 2021)
    # L1 had two variables sharing one strong mode: one or two components.
    assert summary["groups"]["L1"]["kept"] in (1, 2)
    assert "E1" in summary["groups"] and "v850" in summary["groups"]["E3"]["missing"]
    assert "skipped" in summary["groups"]["E5"] or summary["groups"]["E5"]["fields"] == ["u200"]
    assert set(summary["groups"]["E7"]["seasons"]) == {"all"}
    features = pd.read_csv(out / "features_case.csv", index_col="case")
    assert {"E1_pc01", "E7_pc01", "mascarene_pressure", "rmm1", "doy_sin"} <= set(features)
    local = xr.open_dataset(out / "features_local.nc")
    assert "L1_pc01" in local and "rain_mean" in local
    # The frozen transforms give the same numbers on the same cases.
    again = tmp_path / "again"
    reduce.run(derived, again, models, False, cat)
    replay = pd.read_csv(again / "features_case.csv", index_col="case")
    assert np.allclose(replay["E1_pc01"], features["E1_pc01"], equal_nan=True)
    assert np.allclose(
        xr.open_dataset(again / "features_local.nc")["L1_pc01"], local["L1_pc01"], equal_nan=True
    )


# ---------------------------------------------------------------- downloads and readers


def test_s2s_requests_follow_the_catalogue_and_skip_missing_parameters():
    cat = common.catalogue()
    plan = download.s2s_plan(cat, {"missing": ["sm20", "w@500"]})
    kinds = {p["kind"] for p in plan}
    assert "sfc_initial" not in kinds and not any("_w" in k or k == "pl_w" for k in kinds)
    assert {"sfc_instant", "sfc_accumulated", "global_u", "global_v"} <= kinds
    accumulated = next(p for p in plan if p["kind"] == "sfc_accumulated")
    assert accumulated["steps"] == [168, 336] and set(accumulated["params"]) == {"tp", "ttr"}
    request = download.s2s_request(
        date(2025, 1, 2),
        [date(2006, 1, 2), date(2005, 1, 2)],
        "pl",
        ["u", "v"],
        [192, 216],
        "45/-20/-45/180",
        [850, 200],
    )
    assert request["hdate"] == "2005-01-02/2006-01-02" and request["param"] == "131/132"
    assert request["number"] == "1/2/3/4/5/6/7/8/9/10" and request["levelist"] == "850/200"
    assert request["stream"] == "enfh" and request["grid"] == "1.5/1.5"


def test_cases_from_a_model_year_pair_each_date_with_its_hindcast_years(tmp_path):
    from argparse import Namespace

    download.cases_command(
        Namespace(from_cca=None, from_dir=None, model_year=2025, years="2005-2006"),
        common.catalogue(),
        tmp_path,
    )
    cases = common.read_cases(tmp_path / "cases.csv")
    assert all(c.init.weekday() in (0, 3) and c.hdate.year in (2005, 2006) for c in cases)
    assert all((c.hdate.month, c.hdate.day) == (c.init.month, c.init.day) for c in cases)


def test_the_index_readers_parse_the_providers_formats(tmp_path):
    rmm = tmp_path / "rmm.txt"
    rmm.write_text(
        "RMM values\nyear month day RMM1 RMM2 phase amplitude\n"
        "2005 1 2 0.5 -1.0 3 1.1180 Final_value\n2005 1 3 1.E36 1.E36 999 1.E36 Missing\n"
    )
    assert derive._read_rmm(rmm) == {date(2005, 1, 2): (0.5, -1.0, 1.118)}
    daily = tmp_path / "aao.csv"
    daily.write_text("year,month,day,aao_index_cdas\n2005,1,2,-0.53\n")
    assert derive._read_daily_csv(daily) == {date(2005, 1, 2): -0.53}
    table = tmp_path / "qbo.txt"
    table.write_text(
        "  ORIGINAL DATA\nYEAR JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC\n"
        "2005 -10.1 -9.0 -8.0 -7.0 -6.0 -5.0 -4.0 -3.0 -2.0 -1.0 0.0 1.0\n"
        "  ANOMALY\n2005 9 9 9 9 9 9 9 9 9 9 9 9\n"
    )
    values = derive._read_monthly_table(table)
    assert values[(2005, 1)] == -10.1 and values[(2005, 12)] == 1.0  # the first table only
    assert derive._month_before(date(2005, 1, 15)) == (2004, 12)


def test_every_ens_variable_field_and_index_is_derived_for_a_case():
    """ens_case_values on synthetic ensemble arrays (no GRIB): all local variables of L1,
    L2, P1 and N1, the EOF fields and the P2/N7 indices come out finite."""
    lat, lon = np.arange(45, -45.1, -1.5), np.arange(-20, 180.1, 1.5)
    rng = np.random.default_rng(2)
    base = {
        "q": 0.01,
        "t": 280.0,
        "u": 5.0,
        "v": 1.0,
        "gh": 3000.0,
        "w": -0.05,
        "msl": 101000.0,
        "sp": 95000.0,
        "tcw": 40.0,
        "sm20": 0.3,
    }

    class Fake(derive.EnsCase):
        def __init__(self):
            super().__init__({}, date(2005, 1, 2))
            self.lat, self.lon = lat, lon

        def get(self, name, level=None, steps=derive.STEPS):
            shape = (10, len(steps), lat.size, lon.size)
            if name in ("tp", "ttr"):  # accumulated: grows from day 7 to day 14
                start = rng.uniform(0, 0.01, size=shape[:1] + (1,) + shape[2:])
                scale = 0.02 if name == "tp" else -2e6
                return np.concatenate(
                    [start, start + scale * rng.uniform(0.5, 1.5, start.shape)], axis=1
                )
            return base[name] * (1 + 0.05 * rng.normal(size=shape))

    values = derive.ens_case_values(Fake(), common.catalogue())
    cat = common.catalogue()
    ens_local = {n for g in ("L1", "L2", "P1") for n in common.variable_names(cat["groups"][g])}
    assert ens_local <= set(values["local"])
    assert {
        "rain_mean",
        "rain_spread",
        "rain_p10",
        "rain_p90",
        "rain_share_10mm",
        "soil_moisture",
    } <= set(values["local"])
    assert {
        "olr",
        "u850",
        "u200",
        "msl",
        "v850",
        "u925",
        "v925",
        "qflux850",
        "gh850",
        "u100",
        "u700",
        "rain",
    } <= set(values["fields"])
    p2 = {v["name"] for v in cat["groups"]["P2"]["variables"]} - {"soi"}
    n7 = {v["name"] for v in cat["groups"]["N7"]["variables"]}
    assert p2 | n7 <= set(values["index"])
    assert all(np.isfinite(v).all() for v in values["local"].values())
    assert all(np.isfinite(v) for v in values["index"].values())
    assert values["fields"]["olr"].mean() > 0  # outgoing radiation is positive
