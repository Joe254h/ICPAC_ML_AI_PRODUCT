from __future__ import annotations

import io
import logging
import os
from functools import lru_cache
from typing import Any

import numpy as np

from backend.app.db import Repository, now
from backend.app.schemas import Selection
from climate_engine.aggregation import country_mask, weighted_mean
from climate_engine.core import DEMO_LABEL, checksum, config
from climate_engine.forecasts import MockForecastProvider
from climate_engine.models import ArtifactModel, MockForecastModel, RawECMWFModel
from climate_engine.observations import MockObservationProvider, week2_dates
from climate_engine.preprocessing import accumulate_week2, align_exact
from climate_engine.qc import check_dataset
from climate_engine.verification import metrics

logger = logging.getLogger("icpac.pipeline")


class Platform:
    def __init__(self, repository: Repository):
        self.repo = repository
        for model in config("models")["models"]:
            try:
                self.repo.get("model", model["model_id"])
            except KeyError:
                self.repo.save(
                    "model",
                    {
                        **model,
                        "training_period": "synthetic demonstration",
                        "validation_period": "synthetic demonstration",
                        "domain": config()["domain"],
                        "grid": config()["grid_shape"],
                        "created_at": now(),
                        "artifact_path": None,
                        "checksum": checksum(model),
                        "git_commit": os.getenv("GIT_COMMIT", "development"),
                        "metrics": {},
                        "notes": DEMO_LABEL,
                        "validated": True,
                    },
                    model["model_id"],
                )
        for source in config("observations")["sources"]:
            self.repo.save("dataset", MockObservationProvider(source).metadata(), source)
        for cycle in config("forecasts")["cycles"]:
            self.repo.save("forecast_cycle", {"cycle": str(cycle), "mode": "synthetic"}, str(cycle))

    def model(self, model_id: str):
        metadata = self.repo.get("model", model_id)
        if metadata["model_type"] == "mock":
            return MockForecastModel()
        if metadata["model_type"] == "raw":
            return RawECMWFModel()
        return ArtifactModel(
            metadata["model_type"], metadata["artifact_path"], metadata["feature_schema"]
        )

    def calculate(self, selection: Selection) -> dict[str, Any]:
        return self._calculate(selection.model_dump_json())

    @lru_cache(maxsize=96)
    def _calculate(self, selection_json: str) -> dict[str, Any]:
        s = Selection.model_validate_json(selection_json)
        cfg = config()
        if s.country != "GHA" and s.country not in cfg["countries"]:
            raise ValueError("Unknown country")
        start, end = week2_dates(s.cycle)
        forecast = MockForecastProvider(s.provider).load(s.cycle)
        obs = MockObservationProvider(s.observation).load(start, end)
        qc = [check_dataset(forecast, forecast=True), check_dataset(obs, start, end)]
        if any(result["status"] == "FAIL" for result in qc):
            raise ValueError("QC failed: " + str(qc))
        raw = accumulate_week2(forecast)
        observed = obs.precipitation.sum("time", skipna=False)
        corrected, observed = align_exact(self.model(s.model).predict(raw), observed)
        lat, lon = corrected.latitude.values, corrected.longitude.values
        gha_mask = np.zeros(corrected.shape, dtype=bool)
        masks = {country: country_mask(country, lat, lon) for country in cfg["countries"]}
        for mask in masks.values():
            gha_mask |= mask
        mask = gha_mask if s.country == "GHA" else masks[s.country]
        if not mask.any():
            raise ValueError(
                "No grid cells in country at demo resolution; use a finer validated mask"
            )
        f, o, r = corrected.values, observed.values, raw.values
        # Synthetic reference field is explicitly not historical climatology.
        reference = o * 0.92 + 3
        score = metrics(f[mask], o[mask])
        countries = []
        for country, cmask in masks.items():
            country_score = metrics(f[cmask], o[cmask]) if cmask.any() else {}
            countries.append(
                {
                    "country": country,
                    "mean_rainfall_mm": weighted_mean(f, lat, cmask),
                    "anomaly_percent": weighted_mean((f / reference - 1) * 100, lat, cmask),
                    **country_score,
                    "cell_count": int(cmask.sum()),
                    "mask_status": "approximate demonstration",
                }
            )
        comparison = []
        for model_id in ["raw-v1", "mock-v1"]:
            pred = self.model(model_id).predict(raw).values
            comparison.append(
                {
                    "model": self.repo.get("model", model_id)["model_name"],
                    **metrics(pred[mask], o[mask]),
                }
            )
        obs_comparison = []
        for source in cfg_observations():
            other = (
                MockObservationProvider(source)
                .load(start, end)
                .precipitation.sum("time", skipna=False)
            )
            _, aligned = align_exact(corrected, other)
            obs_comparison.append({"source": source, **metrics(f[mask], aligned.values[mask])})
        fields = {
            "corrected": f,
            "raw": r,
            "observed": o,
            "bias": f - o,
            "rmse": np.abs(f - o),
            "improvement": np.abs(r - o) - np.abs(f - o),
            "anomaly": (f / reference - 1) * 100,
        }
        features = []
        dx, dy = float(np.diff(lon)[0]) / 2, float(np.diff(lat)[0]) / 2
        for iy, ix in np.argwhere(mask):
            x, y, value = float(lon[ix]), float(lat[iy]), float(fields[s.layer][iy, ix])
            if not np.isfinite(value):
                continue
            polygon = [
                [x - dx, y - dy],
                [x + dx, y - dy],
                [x + dx, y + dy],
                [x - dx, y + dy],
                [x - dx, y - dy],
            ]
            features.append(
                {
                    "type": "Feature",
                    "properties": {"value": round(value, 3)},
                    "geometry": {"type": "Polygon", "coordinates": [polygon]},
                }
            )
        daily = forecast.precipitation.where(forecast.lead_time.isin(range(8, 15)), drop=True)
        timeseries = [
            {
                "date": str(t)[:10],
                "raw": weighted_mean(daily.values[i], lat, mask),
                "observed": weighted_mean(obs.precipitation.values[i], lat, mask),
            }
            for i, t in enumerate(obs.time.values)
        ]
        model_metadata = self.repo.get("model", s.model)
        provenance = {
            "forecast_cycle": s.cycle,
            "forecast_provider": s.provider,
            "model": model_metadata["model_name"],
            "model_version": model_metadata["version"],
            "model_checksum": model_metadata["checksum"],
            "observation_source": s.observation,
            "observation_version": obs.attrs["version"],
            "code_version": "0.1.0",
            "git_commit": os.getenv("GIT_COMMIT", "development"),
            "pipeline_version": cfg["version"],
            "domain": cfg["domain"],
            "grid": cfg["grid_shape"],
            "start_time": start,
            "end_time": end,
            "creation_timestamp": now(),
            "qc_status": "WARN" if any(item["status"] == "WARN" for item in qc) else "PASS",
            "mode": "synthetic",
            "mask_status": cfg["mask_status"],
            "config_checksum": checksum(cfg),
            "metric_scope": "paired spatial cells, one accumulated seven-day case",
            "anomaly_reference": "synthetic reference; not a historical climatology",
        }
        logger.info(
            "calculation_complete",
            extra={"run_id": checksum(s.model_dump())[:12], "cycle": s.cycle, "model": s.model},
        )
        return {
            "selection": s.model_dump(),
            "label": DEMO_LABEL,
            "period": f"{start}/{end}",
            "metrics": score,
            "mean_rainfall_mm": weighted_mean(f, lat, mask),
            "anomaly_percent": weighted_mean(fields["anomaly"], lat, mask),
            "countries": countries,
            "model_comparison": comparison,
            "observation_comparison": obs_comparison,
            "timeseries": timeseries,
            "map": {"type": "FeatureCollection", "features": features},
            "provenance": provenance,
            "qc": qc,
        }

    def run_verification(self, selection: Selection) -> dict:
        result = self.calculate(selection)
        record = self.repo.save(
            "verification",
            {
                "selection": result["selection"],
                "metrics": result["metrics"],
                "provenance": result["provenance"],
                "created_at": now(),
            },
        )
        self.repo.audit("verification_run", "prototype", record["id"])
        return record

    def png(self, selection: Selection) -> bytes:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        result = self.calculate(selection)
        fig = Figure(figsize=(8, 7), facecolor="#eef4f0")
        ax = fig.subplots()
        cells = result["map"]["features"]
        scatter = ax.scatter(
            [c["geometry"]["coordinates"][0][0][0] for c in cells],
            [c["geometry"]["coordinates"][0][0][1] for c in cells],
            c=[c["properties"]["value"] for c in cells],
            cmap="YlGnBu",
            marker="s",
            s=60,
        )
        from climate_engine.aggregation import boundaries

        for feature in boundaries()["features"]:
            g = feature["geometry"]
            polygons = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            for polygon in polygons:
                points = np.array(polygon[0])
                ax.plot(points[:, 0], points[:, 1], color="#334f44", linewidth=0.7)
        ax.set(
            xlim=(21, 52),
            ylim=(-12, 24),
            xlabel="Longitude",
            ylabel="Latitude",
            title=f"ICPAC Prototype · {selection.layer}\n{result['period']} · {selection.observation}",
        )
        fig.colorbar(scatter, ax=ax, label="%" if selection.layer == "anomaly" else "mm")
        fig.text(0.1, 0.01, DEMO_LABEL, fontsize=8)
        buffer = io.BytesIO()
        FigureCanvasAgg(fig).print_png(buffer)
        return buffer.getvalue()


def cfg_observations() -> list[str]:
    return list(config("observations")["sources"])
