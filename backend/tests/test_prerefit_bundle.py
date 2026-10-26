"""The frozen pre-refit bundle (ICPAC_WEEK2_WEB_MODEL_20261025) on the full 800 x 700 grid.

Parity is checked against the bundle's own runtime and the training code's bilinear
geometry, on labelled synthetic 1.5 degree inputs: these test the software, never skill.
"""

import importlib.util
import shutil
from datetime import date

import numpy as np
import pytest
from scipy import sparse

from backend.tests import bundle_inputs
from climate_engine.core import ROOT
from climate_engine.forecasts import ECMWFS2SForecastProvider
from climate_engine.models.descriptor import load_descriptor
from climate_engine.models.hybrid7_pc17 import POLICIES, apply_policy
from climate_engine.operational.grid import load_grid
from climate_engine.operational.pipeline import REALTIME_REVIEW, run_forecast
from climate_engine.operational.settings import settings
from climate_engine.preprocessing.hybrid7_pc17 import InputContractError

BUNDLE = ROOT / "artifacts" / "bundles" / "ICPAC_WEEK2_WEB_MODEL_20261025"
DESCRIPTORS = {
    "catboost_full": "config/model_registry/icpac_week2_catboost_prerefit_v1.yaml",
    "global_alpha075": "config/model_registry/icpac_week2_alpha075_prerefit_v1.yaml",
    "mam_protected": "config/model_registry/icpac_week2_mam_protected_prerefit_v1.yaml",
    "mbc_only": "config/model_registry/icpac_week2_mbc_only_prerefit_v1.yaml",
}


@pytest.fixture(scope="module")
def grid():
    return load_grid(ROOT / "artifacts" / "domain" / "authoritative_icpac11_mask.npz")


@pytest.fixture(scope="module")
def loaded(grid):
    cfg = settings()
    return {p: load_descriptor(path).verified(grid, cfg) for p, path in DESCRIPTORS.items()}


def runtime():
    spec = importlib.util.spec_from_file_location(
        "icpac_bundle_runtime", BUNDLE / "runtime" / "icpac_week2_inference.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def training_reference(grid, rain, levels):
    """The training code's own reductions (fullgrid_stats_mbc.py geometry, raw_member_week,
    atm_features): statistics on the 1.5 degree grid, then its sparse bilinear matrix."""
    rows, cols = np.nonzero(grid.mask)
    with np.load(BUNDLE / "artifacts" / "authoritative_icpac11_mask.npz") as z:
        yy = np.asarray(z["latitude"], np.float64)[rows]
        xx = np.asarray(z["longitude"], np.float64)[cols]
    lat, lon = bundle_inputs.LAT, bundle_inputs.LON
    iy, ix = np.argsort(lat), np.argsort(lon)
    lat_s, lon_s = lat[iy], lon[ix]
    j = np.searchsorted(lat_s, yy, side="right").clip(1, 26)
    i = np.searchsorted(lon_s, xx, side="right").clip(1, 23)
    jy = (yy - lat_s[j - 1]) / (lat_s[j] - lat_s[j - 1])
    ixr = (xx - lon_s[i - 1]) / (lon_s[i] - lon_s[i - 1])
    cells = np.arange(rows.size)
    columns = np.concatenate(
        [
            iy[j - 1] * 24 + ix[i - 1],
            iy[j - 1] * 24 + ix[i],
            iy[j] * 24 + ix[i - 1],
            iy[j] * 24 + ix[i],
        ]
    )
    weights = np.concatenate([(1 - jy) * (1 - ixr), (1 - jy) * ixr, jy * (1 - ixr), jy * ixr])
    aa = sparse.coo_matrix((weights, (np.tile(cells, 4), columns)), shape=(cells.size, 648)).tocsr()
    data = rain["tp"].values * 1000.0
    week = np.maximum(data[:, 1] - data[:, 0], 0.0)
    raw = np.asarray(aa @ week.mean(0).ravel(), np.float32)
    spread = np.asarray(aa @ week.std(0, ddof=0).ravel(), np.float32)
    a = {k: levels[k].values.astype(np.float64) for k in bundle_inputs.UNITS}
    index = {level: n for n, level in enumerate(bundle_inputs.LEVELS)}

    def g(name, level):
        return a[name][:, :, index[level]]

    q8, q7, u8, v8 = g("q", 850), g("q", 700), g("u", 850), g("v", 850)
    t8, t5, h5, u2, v2 = g("t", 850), g("t", 500), g("gh", 500), g("u", 200), g("v", 200)
    wind = np.hypot(u8, v8)
    derived = [q8, q7, u8, v8, wind, q8 * u8, q8 * v8, q8 * wind, t8, t5, t8 - t5, h5, u2, v2]
    derived.append(np.hypot(u2 - u8, v2 - v8))
    stats = []
    for x in derived:
        member = x.mean(axis=1)
        stats += [member.mean(axis=0).ravel(), member.std(axis=0, ddof=0).ravel()]
    return raw, spread, aa @ np.stack(stats, axis=1)


@pytest.mark.parametrize("initialization", [date(2023, 7, 3), date(2024, 4, 15)])
def test_features_and_policies_match_the_bundle_runtime(grid, loaded, initialization):
    cfg = settings()
    rain = bundle_inputs.rainfall(initialization)
    levels = bundle_inputs.pressure(initialization)
    model = loaded["catboost_full"][1]
    features = model.build_features(rain, initialization, grid, cfg, levels)
    assert features.names == list(features.names) and len(features.names) == 24
    assert all(c["status"] in {"passed", "note"} for c in features.checks)
    raw, spread, atmos = training_reference(grid, rain, levels)
    engine = runtime().ICPACWeek2Predictor(BUNDLE)
    reference = engine.build_features(
        initialization.isoformat(), raw, spread, atmos, operational_feed_verified=True
    )
    np.testing.assert_allclose(features.matrix, reference, rtol=0, atol=2e-5)
    result = model.run(features)
    for policy in POLICIES:
        expected = engine.predict(
            reference, initialization.isoformat(), policy, operational_feed_verified=True
        )
        mine = apply_policy(policy, result.mbc, result.residual, initialization.month)
        np.testing.assert_allclose(mine, expected, rtol=0, atol=1e-4)
    # The full correction is the default: max(MBC + residual, 0), never negative.
    np.testing.assert_allclose(result.hybrid, np.maximum(result.mbc + result.residual, 0))
    assert (result.hybrid >= 0).all()
    if initialization.month in (3, 4, 5):
        mam = loaded["mam_protected"][1].run(features).hybrid
        np.testing.assert_allclose(mam, np.maximum(result.mbc, 0))


def test_policies_clip_and_protect_march_to_may():
    mbc = np.array([0.0, 2.0, 10.0])
    residual = np.array([-1.0, -3.0, 4.0])
    assert apply_policy("catboost_full", mbc, residual, 7).tolist() == [0.0, 0.0, 14.0]
    assert apply_policy("global_alpha075", mbc, residual, 7).tolist() == [0.0, 0.5, 13.0]
    assert apply_policy("mam_protected", mbc, residual, 4).tolist() == [0.0, 2.0, 10.0]
    assert apply_policy("mam_protected", mbc, residual, 6).tolist() == [0.0, 0.5, 13.0]
    assert apply_policy("mbc_only", mbc, None, 7).tolist() == [0.0, 2.0, 10.0]
    with pytest.raises(ValueError, match="needs the CatBoost residual"):
        apply_policy("catboost_full", mbc, None, 7)
    with pytest.raises(ValueError, match="Unknown policy"):
        apply_policy("best", mbc, residual, 7)


def test_registration_reads_the_frozen_contract(loaded):
    fields, model = loaded["catboost_full"]
    assert fields["trees"] == 300 and fields["feature_count"] == 24
    assert fields["features"][6] == "MBC_forecast_mmweek" and fields["features"][-1].endswith("17")
    assert fields["pressure_steps_hours"] == [192, 216, 240, 264, 288, 312, 336]
    assert fields["metrics"]["rainfall_RMSE"] == pytest.approx(14.28011494379281)
    report = fields["bundle"]["independent_report"]
    assert report["rmse"] == pytest.approx(15.203975963894882) and report["cases"] == 551
    assert report["rows"] == 113285600
    assert "after the 2022-2024 scores were seen" in report["selection_note"]
    assert "_" not in report["selection_note"]  # words, not policy codes
    assert fields["descriptor"]["declared_status"] == "experimental"
    mam = loaded["mam_protected"][0]
    assert mam["bundle"]["independent_report"]["rmse"] == pytest.approx(15.270882118994829)
    assert "rainfall_pearson_r" not in mam["metrics"]  # not in the bundle: never invented
    assert loaded["mbc_only"][1].needs_pressure() is False


def test_a_changed_bundle_file_is_refused(tmp_path, monkeypatch, grid):
    root = tmp_path / "artifacts"
    shutil.copytree(BUNDLE, root / "bundles" / BUNDLE.name)
    monkeypatch.setenv("ARTIFACT_ROOT", str(root))
    descriptor = load_descriptor(DESCRIPTORS["catboost_full"])
    descriptor.verify_checksums()
    target = root / "bundles" / BUNDLE.name / "provenance" / "train_fullgrid_ml.py"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Bundle file changed: provenance/train_fullgrid_ml.py"):
        descriptor.verify_checksums()


@pytest.mark.parametrize(
    "change, check",
    [
        ("steps", "upper-air forecast hours"),
        ("members", "ensemble size"),
        ("units", "upper-air variables and units"),
        ("missing", "upper-air member 1"),
        ("negative", "negative rainfall"),
        ("window", "Days 8–14 window"),
    ],
)
def test_incompatible_inputs_fail_closed(grid, loaded, change, check):
    cfg = settings()
    initialization = date(2023, 7, 3)
    rain = bundle_inputs.rainfall(initialization)
    levels = bundle_inputs.pressure(initialization)
    if change == "steps":
        levels = bundle_inputs.pressure(initialization, steps=[168, 192, 216, 240, 264, 288, 312])
    elif change == "members":
        rain = bundle_inputs.rainfall(initialization, members=9)
        levels = bundle_inputs.pressure(initialization, members=9)
    elif change == "units":
        levels["t"].attrs["units"] = "degC"
    elif change == "missing":
        levels["q"].values[0, 0, 0, 10, 10] = np.nan
    elif change == "negative":
        rain["tp"].values[2, 1, 5:9, 5:9] = rain["tp"].values[2, 0, 5:9, 5:9] - 0.01
    elif change == "window":
        cfg["ecmwf"]["rainfall"]["accumulation_steps_hours"] = [144, 336]
    with pytest.raises(InputContractError) as error:
        loaded["catboost_full"][1].build_features(rain, initialization, grid, cfg, levels)
    failed = [c for c in error.value.checks if c["status"] == "failed"]
    assert [c["check"] for c in failed] == [check]


def test_the_pipeline_applies_the_realtime_gate(tmp_path, grid, loaded):
    cfg = settings()
    fields, model = loaded["catboost_full"]
    record = {**fields, "status": "experimental"}
    past, now = date(2023, 7, 3), date(2026, 10, 19)
    for initialization in (past, now):
        bundle_inputs.write(tmp_path, initialization)

    def run(initialization, review=None, which=model, which_record=record):
        tag = initialization.isoformat()
        provider = ECMWFS2SForecastProvider(
            tmp_path / f"ecmwf_s2s_tp_{tag}.nc", tmp_path / f"ecmwf_s2s_pl_{tag}.nc", cfg
        )
        return run_forecast(provider, tag, which, grid, cfg, which_record, realtime_review=review)

    reforecast = run(past)
    p = reforecast.provenance
    assert p["layers"] == ["raw", "mbc", "residual", "hybrid"] and p["primary_layer"] == "hybrid"
    assert p["hybrid_policy"]["policy"] == "catboost_full"
    assert p["hybrid_policy"]["scientific_preselected_policy"] == "mam_protected"
    assert p["realtime_gate"] == {"required": False, "review": None}
    assert p["pressure_steps_hours"] == [192, 216, 240, 264, 288, 312, 336]
    assert all(c["status"] in {"passed", "note"} for c in p["input_checks"])
    assert "max(MBC + CatBoost residual, 0)" in reforecast.dataset["hybrid"].attrs["long_name"]

    waiting = run(now)
    assert waiting.provenance["layers"] == ["raw", "mbc"]
    assert waiting.provenance["products"]["hybrid"] == {
        "status": "in_progress",
        "reason": REALTIME_REVIEW,
    }
    # The checks still ran: the reviewer sees they all passed before confirming.
    assert waiting.provenance["input_checks"][-1]["check"] == "MBC factors"

    review = {"actor": "Joe N", "timestamp": "2026-10-25T10:00:00+00:00", "source": "ecmwf_files"}
    confirmed = run(now, review)
    assert confirmed.provenance["primary_layer"] == "hybrid"
    assert confirmed.provenance["realtime_gate"] == {"required": True, "review": review}
    assert any("reforecasts, not this real-time skill" in n for n in confirmed.notes)

    mbc_fields, mbc_model = loaded["mbc_only"]
    fallback = run(past, which=mbc_model, which_record={**mbc_fields, "status": "experimental"})
    assert fallback.provenance["layers"] == ["raw", "mbc"]
    assert fallback.provenance["primary_layer"] == "mbc"
    assert fallback.provenance["products"]["hybrid"]["status"] == "not_produced"
    np.testing.assert_allclose(
        fallback.dataset["mbc"].values[grid.mask], reforecast.dataset["mbc"].values[grid.mask]
    )


def test_the_decided_model_issues_the_hybrid_once_the_realtime_input_is_confirmed(
    tmp_path, monkeypatch
):
    """Through the API, with the committed decision on the model in use: the first 2026
    run of the pre-refit model passes every input check and waits for the reviewer; after
    the confirmation the weekly run issues a new forecast with the MBC + AI/ML layer."""
    from fastapi.testclient import TestClient

    from backend.app.main import create_app
    from backend.tests import ecmwf_mirror
    from backend.tests.test_forecasts import PNG
    from backend.tests.test_inputs import wait
    from climate_engine.cartography import icpac_maps

    key = "test-bulletin-operator-key-00000000"
    for name, value in {
        "BULLETIN_OPERATOR_KEY": key,
        "AUTO_REGISTER_MODELS": "true",
        "RUN_ROOT": tmp_path / "runs",
        "FORECAST_INPUT_ROOT": tmp_path / "inputs",
        "DATA_ROOT": tmp_path / "observations",
    }.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.delenv("MODEL_DECISION_PATH")
    monkeypatch.delenv("ARTIFACT_ROOT", raising=False)
    monkeypatch.setattr(
        "climate_engine.inputs.ecmwf_opendata.member_numbers", lambda: [*range(1, 11)]
    )
    monkeypatch.setattr(icpac_maps, "render_png", lambda *args, **kwargs: PNG)
    steps = (192, 216, 240, 264, 288, 312, 336)
    ecmwf_mirror.build(tmp_path / "mirror", date(2026, 10, 25), 10, pressure_steps=steps)
    model_id = "icpac_week2_catboost_prerefit_v1"
    weekly = {"action": "run_forecast", "initialization": "2026-10-25", "actor": "Joe254h"}
    with ecmwf_mirror.serve(tmp_path / "mirror") as url:
        monkeypatch.setenv("ECMWF_OPENDATA_MIRRORS", url)
        app = create_app(f"sqlite:///{tmp_path / 'db.sqlite'}")
        with TestClient(app, headers={"Authorization": f"Bearer {key}"}) as client:
            assert client.get("/models/current").json()["model"]["model_id"] == model_id
            done = wait(client, client.post("/operations", json=weekly).json(), 600)
            assert done["status"] == "complete", done
            waiting = client.get(f"/forecasts/{done['result']['forecast_id']}").json()
            assert waiting["model_id"] == model_id and waiting["primary_layer"] == "mbc"
            assert waiting["products"]["hybrid"] == {
                "status": "in_progress",
                "reason": REALTIME_REVIEW,
            }
            checks = waiting["provenance"]["input_checks"]
            assert len(checks) == 26 and {c["status"] for c in checks} == {"passed"}

            review = client.post(
                f"/models/{model_id}/realtime-review",
                json={
                    "source": "ecmwf_opendata",
                    "forecast_id": waiting["forecast_id"],
                    "actor": "Joe254h",
                    "confirmed": True,
                    "comment": "Every input check passed on the 25 October run",
                },
            )
            assert review.status_code == 200, review.text

            done = wait(client, client.post("/operations", json=weekly).json(), 600)
            issued = client.get(f"/forecasts/{done['result']['forecast_id']}").json()
            assert issued["forecast_id"] != waiting["forecast_id"]
            assert issued["primary_layer"] == "hybrid"
            assert issued["products"]["hybrid"] == {"status": "available"}
            assert issued["provenance"]["realtime_gate"]["review"]["actor"] == "Joe254h"
            # The confirmed run is the one the week keeps: a retry reuses it.
            again = wait(client, client.post("/operations", json=weekly).json(), 600)
            assert again["result"]["forecast_id"] == issued["forecast_id"]
