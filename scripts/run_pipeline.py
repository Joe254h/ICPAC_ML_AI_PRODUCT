"""Idempotent prototype runner; forecast and observation events have separate state."""

import argparse
import json
import os
from uuid import uuid4

from backend.app.db import Repository
from backend.app.schemas import Selection
from backend.app.services.platform import Platform
from climate_engine.core import ROOT, checksum
from climate_engine.provenance import code_version, configuration_checksum


def run(selection: Selection, trigger: str = "forecast", force: bool = False) -> dict:
    folder = ROOT / "data" / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    platform = Platform(Repository())
    platform.observation(selection.observation)
    platform.model(selection.model)
    dataset = platform.repo.get("dataset", selection.observation)
    model = platform.repo.get("model", selection.model)
    signature = checksum(
        {
            "selection": selection.model_dump(),
            "config": configuration_checksum(),
            "trigger": trigger,
            "git_commit": code_version(),
            "dataset": dataset,
            "model_checksum": model["checksum"],
        }
    )
    state = folder / f"{trigger}-{selection.observation}.state.json"
    if state.is_file() and not force and json.loads(state.read_text())["signature"] == signature:
        return {"status": "unchanged", "trigger": trigger}
    lock = folder / "pipeline.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(
            "Pipeline lock exists. Check active run before removing a stale lock."
        ) from exc
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        run_id = str(uuid4())
        if trigger == "observation":
            result = platform.run_verification(selection)
        else:
            result = platform.calculate(selection)
            out = folder / run_id
            out.mkdir()
            (out / "forecast.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            (out / "rainfall.png").write_bytes(platform.png(selection))
            (out / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "sha256": checksum(result),
                        "provenance": result["provenance"],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            platform.repo.save(
                "product_run",
                {"run_id": run_id, "location": str(out), "provenance": result["provenance"]},
                run_id,
            )
        temporary = state.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"signature": signature, "run_id": run_id}), encoding="utf-8"
        )
        temporary.replace(state)
        return {"status": "success", "run_id": run_id, "trigger": trigger}
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycle", default="2026-09-28")
    parser.add_argument("--observation", default="CHIRPS")
    parser.add_argument("--model", default="mock-v1")
    parser.add_argument("--trigger", choices=["forecast", "observation"], default="forecast")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                Selection(cycle=args.cycle, observation=args.observation, model=args.model),
                args.trigger,
                args.force,
            )
        )
    )
