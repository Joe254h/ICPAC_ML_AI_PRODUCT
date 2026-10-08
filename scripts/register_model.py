"""Register a model through the same service the API uses.

Operational model (verifies every artifact first; nothing is recorded if a check fails):

    python -m scripts.register_model \\
        --descriptor config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml --actor Joe254h

Demonstration model on the synthetic grid (one-feature schema):

    python -m scripts.register_model --name demo --version 1.0.0 --type catboost \\
        --artifact artifacts/demo.cbm --feature-schema rainfall_total_v1
"""

import argparse
import json

from backend.app.db import Repository
from backend.app.schemas import RegisterRequest
from backend.app.services.platform import Platform
from backend.app.services.registry import ModelRegistry

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", help="operational model descriptor (YAML)")
    parser.add_argument("--actor", default="registry", help="who registers the model")
    parser.add_argument("--name")
    parser.add_argument("--version")
    parser.add_argument("--artifact")
    parser.add_argument(
        "--type", choices=["catboost", "lightgbm", "xgboost", "random_forest", "abc"]
    )
    parser.add_argument("--feature-schema")
    parser.add_argument("--training-period", default="not supplied")
    parser.add_argument("--validation-period", default="not supplied")
    args = parser.parse_args()
    registry = ModelRegistry(Platform(Repository()))
    if args.descriptor:
        record = registry.register_descriptor(args.descriptor, args.actor)
        record.pop("descriptor_data", None)
        print(json.dumps(record, indent=2, default=str))
        raise SystemExit(0)
    missing = [
        k for k in ("name", "version", "artifact", "type", "feature_schema") if not getattr(args, k)
    ]
    if missing:
        parser.error(
            "demo registration needs --" + ", --".join(m.replace("_", "-") for m in missing)
        )
    body = RegisterRequest(
        model_id=f"{args.name}_{args.version.replace('.', '_')}",
        model_name=args.name,
        version=args.version,
        artifact_path=args.artifact,
        model_type=args.type,
        feature_schema=args.feature_schema,
        training_period=args.training_period,
        validation_period=args.validation_period,
    )
    print(json.dumps(registry.register(body), indent=2))
