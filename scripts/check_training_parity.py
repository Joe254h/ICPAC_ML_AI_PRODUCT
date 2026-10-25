"""Compare a supplied full-domain HPC golden NPZ with the operational inference path.

Requires the real frozen pressure steps and matching rainfall/pressure fields.
The golden NPZ contains names, features, residual and hybrid (no pickled objects).
It writes a report and exits nonzero on differences; never changes a model's status.
"""

import argparse
import json
from datetime import date
from pathlib import Path

import numpy as np

from climate_engine.core import checksum
from climate_engine.forecasts import ECMWFS2SForecastProvider
from climate_engine.models.descriptor import load_descriptor
from climate_engine.operational.parity import compare
from climate_engine.operational.pipeline import grid_from_config
from climate_engine.operational.settings import settings
from climate_engine.provenance import file_checksum


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("descriptor", "rainfall", "pressure", "golden", "golden-sha256", "output"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--initialization", type=date.fromisoformat, required=True)
    parser.add_argument("--atol", type=float, default=1e-6)
    parser.add_argument("--rtol", type=float, default=1e-6)
    args = parser.parse_args()
    golden_path = Path(args.golden)
    if file_checksum(golden_path) != args.golden_sha256:
        raise ValueError("The supplied HPC golden case checksum changed")
    cfg = settings()
    grid = grid_from_config(cfg)
    fields, model = load_descriptor(args.descriptor).verified(grid, cfg)
    provider = ECMWFS2SForecastProvider(args.rainfall, args.pressure, cfg)
    cycle = args.initialization.isoformat()
    # The model's own preprocessing (Atmos37, or the frozen bundle's training order).
    features = model.build_features(
        provider.load(cycle), args.initialization, grid, cfg, provider.load_pressure(cycle)
    )
    prediction = model.run(features)
    if prediction.residual is None or prediction.hybrid is None:
        raise ValueError("A full hybrid run is required for training parity")
    with np.load(golden_path, allow_pickle=False) as golden:
        report = compare(
            model.names,
            features.matrix,
            prediction.residual,
            prediction.hybrid,
            golden,
            atol=args.atol,
            rtol=args.rtol,
        )
    report.update(
        initialization=cycle,
        model_id=fields["model_id"],
        artifact_checksums=fields["artifact_checksums"],
        configuration_sha256=checksum(cfg),
        golden_sha256=args.golden_sha256,
        rainfall_sha256=file_checksum(Path(args.rainfall)),
        pressure_sha256=file_checksum(Path(args.pressure)),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Training parity: {report['status']}; report SHA256: {file_checksum(output)}")
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
