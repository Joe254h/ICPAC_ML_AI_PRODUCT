"""The Copilot's only access to platform data is this explicit tool allowlist."""

import numpy as np

from backend.app.schemas import Selection
from climate_engine.core import config

TOOLS = (
    "get_latest_forecast",
    "get_country_forecast",
    "get_verification_metrics",
    "compare_models",
    "compare_observations",
    "get_qc_status",
    "get_available_datasets",
    "get_model_metadata",
    "get_recent_products",
    "get_bulletin_context",
)


class ClimateTools:
    def __init__(self, platform):
        self.platform = platform

    def call(self, name: str, selection: Selection) -> dict:
        if name not in TOOLS:
            raise ValueError("Tool is not approved")
        if name == "get_available_datasets":
            return {
                "datasets": self.platform.repo.list("dataset"),
                "unavailable": config("observations").get("placeholders", []),
            }
        if name == "get_model_metadata":
            return self.platform.repo.get("model", selection.model)
        if name == "get_recent_products":
            return {"products": self.platform.repo.list("product_run")[-10:]}
        if name == "get_qc_status":
            failures = [
                j for j in self.platform.repo.list("job") if j["status"] in {"failed", "blocked"}
            ]
            return {"qc": self.platform.calculate(selection)["qc"], "failed_jobs": failures[-5:]}
        result = self.platform.calculate(selection)
        common = {
            "selection": result["selection"],
            "period": result["period"],
            "label": result["label"],
            "provenance": result["provenance"],
        }
        if name == "compare_models":
            return {**common, "comparison": result["model_comparison"]}
        if name == "compare_observations":
            return {**common, "comparison": result["observation_comparison"]}
        if name == "get_verification_metrics":
            return {**common, "metrics": result["metrics"]}
        if name == "get_bulletin_context":
            return {
                **common,
                "mean_rainfall_mm": result["mean_rainfall_mm"],
                "anomaly_percent": result["anomaly_percent"],
                "metrics": result["metrics"],
                "countries": result["countries"],
                "qc": result["qc"],
            }
        values = [f["properties"]["value"] for f in result["map"]["features"]]
        return {
            **common,
            "mean_rainfall_mm": result["mean_rainfall_mm"],
            "anomaly_percent": result["anomaly_percent"],
            "metrics": result["metrics"],
            "countries": result["countries"],
            "map_layer": selection.layer,
            "positive_map_cells": sum(v > 0 for v in values),
            "map_cell_count": len(values),
            "map_mean": float(np.mean(values)) if values else None,
        }
