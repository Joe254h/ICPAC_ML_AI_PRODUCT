"""Fixed scientific stages shared by local and SLURM workers."""

import json
import os
from pathlib import Path

from backend.app.db import now
from backend.app.schemas import Selection
from climate_engine.core import ROOT
from climate_engine.forecasts import MockForecastProvider
from climate_engine.observations import week2_dates
from climate_engine.preprocessing import accumulate_week2, align_exact
from climate_engine.provenance import file_checksum
from climate_engine.qc import check_dataset

STAGES = ("download", "qc", "preprocess", "features", "inference", "verification", "products")


def run_stage(platform, selection: Selection, stage: str, run_id: str) -> str:
    if stage not in STAGES:
        raise ValueError("Unknown fixed pipeline stage")
    start, end = week2_dates(selection.cycle)
    forecast = MockForecastProvider(selection.provider).load(selection.cycle)
    observation = platform.observation(selection.observation).load(start, end)
    if stage == "download":
        return "Loaded configured adapters. Forecast is synthetic; no external download."
    qc = [check_dataset(forecast, forecast=True), check_dataset(observation, start, end)]
    if any(item["status"] == "FAIL" for item in qc):
        raise ValueError("QC failed: " + str(qc))
    if stage == "qc":
        return "Mandatory dataset QC passed: " + json.dumps(qc)
    raw = accumulate_week2(forecast)
    observed = observation.precipitation.sum("time", skipna=False)
    align_exact(raw, observed)
    if stage in {"preprocess", "features"}:
        return f"Selected Days 8–14, exact alignment; feature schema {raw.attrs['feature_schema']}."
    prediction = platform.model(selection.model).predict(raw)
    align_exact(prediction, observed)
    if stage == "inference":
        return "Inference completed with finite, aligned rainfall output."
    if stage == "verification":
        record = platform.run_verification(selection)
        return f"Persisted verification {record['id']}: " + json.dumps(record["metrics"])
    result = platform.calculate(selection)
    output = Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs"))) / run_id
    output.mkdir(parents=True, exist_ok=True)
    (output / "forecast.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (output / "rainfall.png").write_bytes(platform.png(selection))
    files = {name: file_checksum(output / name) for name in ("forecast.json", "rainfall.png")}
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "files": files,
                "provenance": result["provenance"],
                "created_at": now(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    platform.repo.save(
        "product_run",
        {
            "location": str(output),
            "provenance": result["provenance"],
            "created_at": now(),
            "files": files,
        },
        run_id,
    )
    return "Generated checksum-tracked forecast JSON, PNG and manifest."
