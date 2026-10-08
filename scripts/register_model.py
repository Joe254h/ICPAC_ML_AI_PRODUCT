"""Register an operational model through the same service the API uses (every artifact is
verified first; nothing is recorded if a check fails):

    python -m scripts.register_model \
        --descriptor config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml --actor Joe254h
"""

import argparse
import json

from backend.app.db import Repository
from backend.app.services.platform import Platform
from backend.app.services.registry import ModelRegistry

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", required=True, help="operational model descriptor (YAML)")
    parser.add_argument("--actor", default="registry", help="who registers the model")
    args = parser.parse_args()
    record = ModelRegistry(Platform(Repository())).register_descriptor(args.descriptor, args.actor)
    record.pop("descriptor_data", None)
    print(json.dumps(record, indent=2, default=str))
