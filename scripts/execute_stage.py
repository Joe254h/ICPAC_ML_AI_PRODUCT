"""Trusted SLURM entry point; the stage name is an allowlist, never a command."""

import argparse
from pathlib import Path
from uuid import UUID

from backend.app.db import Repository
from backend.app.schemas import Selection
from backend.app.services.platform import Platform
from hpc.pipeline import STAGES, run_stage

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection-file", type=Path, required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    UUID(args.run_id)
    selection = Selection.model_validate_json(args.selection_file.read_text(encoding="utf-8"))
    print(run_stage(Platform(Repository()), selection, args.stage, args.run_id))
