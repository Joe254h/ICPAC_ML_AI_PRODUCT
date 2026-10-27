"""The frozen MBC + CatBoost residual models (Hybrid7 + 17 atmospheric PCs).

Two bundles share the 24 inputs, the runtime and the policies; each manifest.json pins
every file's SHA256 and the descriptor pins the manifest and states the training years:

- artifacts/bundles/ICPAC_WEEK2_WEB_MODEL_20261025: the pre-refit model, trained
  2005-2019, validated 2020-2021 and tested once on 2022-2024 (551 cases) on the HPC.
- artifacts/bundles/ICPAC_WEEK2_CATBOOST_FINAL_REFIT_2005_2021: the final refit on all
  development years 2005-2021 (MBC, PCA and CatBoost refitted; no validation period), with
  a retrospective 2022-2024 comparison (those years had been consulted to choose the policy).

Per domain cell:

    residual       = CatBoost(24 predictors)
    catboost_full  = max(MBC + residual, 0)
    global_alpha075 = 0.25 * max(MBC, 0) + 0.75 * catboost_full
    mam_protected  = max(MBC, 0) for March-May initializations, else global_alpha075
    mbc_only       = max(MBC, 0)

The policy is fixed by the reviewed descriptor; the formulas are those of the bundle's
runtime (runtime/icpac_week2_inference.py). Nothing here downloads data or fits anything.
"""

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from climate_engine.models.residual import InferenceResult, ResidualMBCModel, combine
from climate_engine.models.runtime import ModelArtifactError, load_estimator
from climate_engine.operational.corrections import MBCParameters
from climate_engine.operational.grid import DomainGrid
from climate_engine.preprocessing import hybrid7_pc17 as features
from climate_engine.preprocessing.atmos37 import FeatureSet, RainfallSet
from climate_engine.provenance import file_checksum

FAMILY = "hybrid7_pc17"
N_COMPONENTS = 17
POLICIES = {
    "catboost_full": "max(MBC + CatBoost residual, 0)",
    "global_alpha075": "0.25 × MBC + 0.75 × max(MBC + CatBoost residual, 0)",
    "mam_protected": "MBC for March–May initializations, otherwise the 75% blend",
    "mbc_only": "MBC alone (fallback)",
}
# Rows of the bundle's independent 2022-2024 summary (verification/global_skill_summary.csv).
INDEPENDENT_ROW = {
    "catboost_full": "CatBoost",
    "global_alpha075": "GlobalAlpha075",
    "mam_protected": "MAMProtected",
    "mbc_only": "MBC",
}
MAM = (3, 4, 5)


def apply_policy(policy: str, mbc: np.ndarray, residual: np.ndarray | None, month: int):
    """Final rainfall of a policy, as the bundle's ``predict`` computes it."""
    base = np.maximum(np.asarray(mbc, dtype=np.float64), 0.0)
    if policy not in POLICIES:
        raise ValueError(f"Unknown policy {policy!r}; known: {sorted(POLICIES)}")
    if policy == "mbc_only" or (policy == "mam_protected" and month in MAM):
        return base
    if residual is None:
        raise ValueError(f"The {policy} policy needs the CatBoost residual")
    full = combine(base, residual)
    out = full if policy == "catboost_full" else 0.25 * base + 0.75 * full
    if not np.isfinite(out).all() or (out < 0).any():
        raise ModelArtifactError("The policy produced non-finite or negative rainfall")
    return out


def verify_bundle(manifest: Path, expected_sha256: str) -> dict[str, str]:
    """Check the manifest against the descriptor, then every file it lists."""
    if file_checksum(manifest) != expected_sha256:
        raise ValueError("The bundle manifest checksum does not match the descriptor")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    root = manifest.parent
    for name, digest in data["files_sha256"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise FileNotFoundError(f"Bundle file missing: {name}")
        if file_checksum(path) != digest:
            raise ValueError(f"Bundle file changed: {name}")
    return dict(data["files_sha256"])


@dataclass(frozen=True)
class PCAProjection:
    mean: np.ndarray  # (30,)
    scale: np.ndarray  # (30,)
    basis: np.ndarray  # (30, 17): the first 17 components, transposed

    def project(self, atmos30: np.ndarray) -> np.ndarray:
        x = np.asarray(atmos30, dtype=np.float64)
        if x.ndim != 2 or x.shape[1] != self.mean.size:
            raise ValueError(f"Expected (cells, {self.mean.size}) atmospheric predictors")
        return ((x - self.mean) / self.scale) @ self.basis


def training_years(period: str) -> list[int]:
    """The years of a descriptor's training period, such as 2005-2021."""
    first, last = (int(y) for y in str(period).split("-"))
    return list(range(first, last + 1))


def _span(years: list[int]) -> str:
    return f"{years[0]}-{years[-1]}"


def load_pca(path: Path, cells: int, years: list[int]) -> PCAProjection:
    with np.load(path, allow_pickle=False) as z:
        names = [str(n) for n in z["feature_names"]]
        if names != list(features.ATMOS30):
            raise ValueError("PCA feature order differs from the 30 training predictors")
        if [int(y) for y in z["training_years"]] != years:
            raise ValueError(f"The PCA must be fitted on the training years {_span(years)} only")
        if int(z["cell_count"]) != cells:
            raise ValueError(f"PCA was fitted on {int(z['cell_count'])} cells, grid has {cells}")
        mean = np.asarray(z["mean"], dtype=np.float64)
        scale = np.asarray(z["scale"], dtype=np.float64)
        components = np.asarray(z["components"], dtype=np.float64)
    if mean.shape != (30,) or scale.shape != (30,) or components.shape[1] != 30:
        raise ValueError("PCA dimensions are not those of the 30 atmospheric predictors")
    if components.shape[0] < N_COMPONENTS or not (scale > 0).all():
        raise ValueError("PCA needs 17 components and a positive scale")
    if not (np.isfinite(mean).all() and np.isfinite(components).all()):
        raise ValueError("PCA arrays are not finite")
    return PCAProjection(mean, scale, components[:N_COMPONENTS].T.copy())


def load_factors(
    path: Path, grid: DomainGrid, bounds: tuple[float, float], years: list[int]
) -> MBCParameters:
    """Monthly MBC factors (prior 500, cap 3) in the authoritative cell order."""
    rows, cols = np.unravel_index(grid.domain_cells, grid.shape)
    with np.load(path, allow_pickle=False) as z:
        if not (np.array_equal(z["row_indices"], rows) and np.array_equal(z["col_indices"], cols)):
            raise ValueError("MBC factor cells differ from the authoritative mask order")
        if not (
            np.allclose(z["latitude"], grid.cell_latitude, atol=1e-4)
            and np.allclose(z["longitude"], grid.cell_longitude, atol=1e-4)
        ):
            raise ValueError("MBC factor coordinates differ from the authoritative grid")
        # The pre-refit bundle names the month axis "month", the refit "months".
        months = z["month"] if "month" in z.files else z["months"]
        if [int(m) for m in months] != list(range(1, 13)):
            raise ValueError("MBC factors must cover calendar months 1-12 in order")
        if [int(y) for y in z["train_years"]] != years:
            raise ValueError(f"MBC factors must be estimated on the training years {_span(years)}")
        factors = np.asarray(z["factors"], dtype=np.float64)
        chosen = str(z["chosen_model"])
    if chosen != "MBC_monthly_prior500_cap3":
        raise ValueError(f"MBC artifact holds {chosen}, not MBC_monthly_prior500_cap3")
    if factors.shape != (12, grid.domain_cells.size) or not np.isfinite(factors).all():
        raise ValueError("MBC factors must be finite with shape (12, cells)")
    low, high = bounds
    if factors.min() < low - 1e-6 or factors.max() > high + 1e-6:
        raise ValueError(f"MBC factors fall outside the frozen bounds [{low}, {high}]")
    # The bundle stores factors directly; there is no forecast-mean floor to apply.
    return MBCParameters(factors, low, high, 0.0)


def independent_summary(path: Path, policy: str) -> dict[str, float]:
    """The HPC's 2022-2024 summary row for this policy (reported, not re-scored)."""
    with path.open(newline="", encoding="utf-8") as stream:
        rows = {row["model"]: row for row in csv.DictReader(stream)}
    row = rows[INDEPENDENT_ROW[policy]]
    out = {
        "rows": int(row["rows"]),
        "rmse": float(row["rmse"]),
        "mae": float(row["mae"]),
        "bias": float(row["bias"]),
        "pearson_r": float(row["pearson_r"]),
    }
    if row.get("anomaly_correlation"):
        out["anomaly_correlation"] = float(row["anomaly_correlation"])
    return out


def validation_scores(metrics: dict, policy_manifest: dict, policy: str) -> dict[str, float]:
    """2020-2021 validation scores of the policy, in the registry's metric names."""
    if policy == "catboost_full":
        source = metrics["summary"]["ML"]
    elif policy == "mbc_only":
        source = metrics["summary"]["MBC"]
    elif policy == "global_alpha075":
        source = policy_manifest["comparator"]["metrics"]
    else:  # mam_protected: the manifest records no correlation for it
        source = policy_manifest["primary_candidate"]
    out = {
        "rainfall_RMSE": float(source["rmse"]),
        "rainfall_MAE": float(source["mae"]),
        "rainfall_bias": float(source["bias"]),
    }
    if "pearson_r" in source:
        out["rainfall_pearson_r"] = float(source["pearson_r"])
    return out


class MBCHybrid7PC17CatBoost(ResidualMBCModel):
    """CatBoost residual on Hybrid7 + 17 PCs over the bundle's monthly MBC."""

    def __init__(
        self,
        estimator: Any,
        names: list[str],
        mbc: MBCParameters,
        info: dict[str, Any],
        pca: PCAProjection,
        policy: str,
        steps: list[int],
        training_members: int,
        realtime_from: date,
    ):
        super().__init__(estimator, names, mbc, info, "catboost", FAMILY)
        self.pca, self.policy, self.steps = pca, policy, steps
        self.training_members, self.realtime_from = training_members, realtime_from

    @classmethod
    def load(cls, descriptor: Any, grid: DomainGrid, cfg: dict) -> "MBCHybrid7PC17CatBoost":
        d = descriptor.data
        policy = str(d["policy"])
        if policy not in POLICIES:
            raise ValueError(f"Unknown policy {policy!r}; known: {sorted(POLICIES)}")
        schema = json.loads(descriptor.artifact("feature_schema").read_text(encoding="utf-8"))
        names = [str(n) for n in schema["features"]]
        locked = list(cfg["feature_schemas"][d["feature_schema"]])
        if names != list(features.FEATURES) or names != locked:
            raise ValueError("The bundle's feature schema differs from the locked 24 inputs")
        cells = grid.domain_cells.size
        if int(schema["cell_count"]) != cells or list(schema["full_grid"]) != list(grid.shape):
            raise ValueError("The bundle's grid differs from the authoritative grid")
        if schema.get("rainfall_units") != "mm/week":
            raise ValueError("The bundle's rainfall units must be mm/week")
        steps = [int(h) for h in d["pressure_steps_hours"]]
        if len(steps) != 7:
            raise ValueError("pressure_steps_hours must list the seven training leads")
        low, high = (float(v) for v in d["mbc_factor_bounds"])
        years = training_years(d["training_period"])
        mbc = load_factors(descriptor.artifact("mbc"), grid, (low, high), years)
        pca = load_pca(descriptor.artifact("pca"), cells, years)
        estimator = load_estimator("catboost", descriptor.artifact("model"))
        if type(estimator).__name__ != "CatBoostRegressor":
            raise ModelArtifactError("Expected a CatBoostRegressor artifact")
        if len(estimator.feature_names_) != len(names):
            raise ModelArtifactError(
                f"CatBoost expects {len(estimator.feature_names_)} features, not {len(names)}"
            )
        if estimator.get_cat_feature_indices():
            raise ModelArtifactError("The model has no categorical features")
        trees = int(estimator.tree_count_)
        if d.get("expected_trees") is not None and trees != int(d["expected_trees"]):
            raise ModelArtifactError(f"Model has {trees} trees, expected {d['expected_trees']}")
        params = estimator.get_all_params()
        policies = json.loads(descriptor.artifact("policies").read_text(encoding="utf-8"))
        info = {
            "trees": trees,
            "feature_names_in_artifact": "positional",
            "loss_function": params.get("loss_function"),
            "depth": params.get("depth"),
            "learning_rate": params.get("learning_rate"),
            "random_seed": params.get("random_seed"),
            "policy": policy,
            "policy_definition": POLICIES[policy],
            "training_years": _span(years),
            "scientific_preselected_policy": policies.get("scientific_preselected_primary"),
            "default_basis": policies.get("default_basis")
            or policies.get("policy_selection_context"),
            "independent_test_reuse_warning": policies.get("independent_test_reuse_warning"),
            "pressure_steps_hours": steps,
            "training_members": int(d["ensemble_members"]),
            "realtime_gate_from": str(d["realtime_gate_from"]),
        }
        model = cls(
            estimator,
            names,
            mbc,
            info,
            pca,
            policy,
            steps,
            int(d["ensemble_members"]),
            date.fromisoformat(str(d["realtime_gate_from"])),
        )
        model.smoke_test()
        return model

    # ------------------------------------------------------------------ pipeline hooks

    def pressure_steps(self, cfg: dict) -> list[int] | None:
        return list(self.steps)

    def needs_pressure(self) -> bool:
        return self.policy != "mbc_only"

    @property
    def produces_hybrid(self) -> bool:
        return self.policy != "mbc_only"

    def realtime_gated(self, initialization: date) -> bool:
        """Runs from this date on need a reviewer's confirmation of the real-time feed."""
        return initialization >= self.realtime_from

    def build_features(self, rainfall, initialization, grid, cfg, pressure=None) -> FeatureSet:
        return features.build(self, rainfall, initialization, grid, cfg, pressure)

    def build_rainfall(self, rainfall, initialization, grid, cfg) -> RainfallSet:
        return features.rainfall_only(self, rainfall, initialization, grid, cfg)

    def run(self, feature_set: FeatureSet) -> InferenceResult:
        residual = self.predict_residual(feature_set.matrix, feature_set.names)
        mbc = feature_set.column("MBC_forecast_mmweek")
        month = feature_set.initialization.month
        hybrid = apply_policy(self.policy, mbc, residual, month)
        return InferenceResult(
            raw=feature_set.columns["X_mean"],
            mbc=mbc,
            residual=residual,
            hybrid=hybrid,
            metadata={
                "algorithm": self.algorithm,
                "family": self.family,
                "baseline": self.baseline,
                "features": self.n_features,
                "mbc_month": feature_set.mbc_month,
                "doy_date": feature_set.doy_date.isoformat(),
                "members": feature_set.members,
                "notes": list(feature_set.notes),
                "checks": list(feature_set.checks),
                "hybrid_definition": f"Week-2 rainfall: {POLICIES[self.policy]}",
                **self.info,
            },
        )
