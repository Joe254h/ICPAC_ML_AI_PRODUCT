"""Register native artifacts through the same service used by the API."""

import argparse
import json

from backend.app.db import Repository
from backend.app.schemas import RegisterRequest
from backend.app.services.platform import Platform
from backend.app.services.registry import ModelRegistry

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--type", required=True, choices=["catboost", "lightgbm", "xgboost", "abc"])
    parser.add_argument("--feature-schema", required=True)
    parser.add_argument("--training-period", default="not supplied")
    parser.add_argument("--validation-period", default="not supplied")
    args = parser.parse_args()
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
    print(json.dumps(ModelRegistry(Platform(Repository())).register(body), indent=2))
