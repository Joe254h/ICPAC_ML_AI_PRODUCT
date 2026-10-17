"""SLURM bridge run on the HPC host, with a pinned operator-owned job script.

No SSH credentials or shell command can be supplied through the public website.
Submission uses argv, closed stdin and SLURM's parsable protocol. Uncertain
submissions are reconciled instead of blindly resubmitted after a restart.
"""

import json
import os
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from backend.app.db import now
from climate_engine.provenance import file_checksum


def configured_script() -> Path:
    if os.getenv("ENABLE_SLURM", "false") != "true":
        raise ValueError("SLURM execution is disabled")
    root = Path(os.environ["HPC_SCRIPT_ROOT"]).resolve()
    path = Path(os.environ["HPC_WORKFLOW_SCRIPT"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("The HPC script must be inside its approved script directory")
    expected = os.getenv("HPC_WORKFLOW_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or file_checksum(path) != expected:
        raise ValueError("The HPC job script differs from its approved checksum")
    return path


def command(arguments: list[str]) -> str:
    result = subprocess.run(
        arguments, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30, check=False
    )
    if result.returncode:
        # Do not return the host's stderr (which may contain connection/account details).
        raise RuntimeError(f"{arguments[0]} failed; inspect the private HPC logs")
    return result.stdout.strip()


class HPCService:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    def status(self) -> dict:
        enabled = os.getenv("ENABLE_SLURM", "false") == "true"
        valid = False
        if enabled:
            try:
                configured_script()
                valid = True
            except (KeyError, OSError, ValueError):
                pass
        try:
            checked = self.repo.get("integration_check", "hpc-connection-check")
        except KeyError:
            checked = {}
        return {
            "enabled": enabled,
            "script_approved": valid,
            "connection_verified": enabled and valid and bool(checked.get("connected")),
            "last_checked_at": checked.get("checked_at"),
            "jobs": self.repo.list("hpc_job"),
            "note": "Run the bridge on the SLURM host. Import its completed forecast package through the existing checked package interface.",
        }

    def _find(self, name: str) -> list[tuple[str, str]]:
        rows = command(
            [
                "sacct",
                "--noheader",
                "--allocations",
                "--name",
                name,
                "--format=JobIDRaw,State",
                "--parsable2",
            ]
        )
        self.repo.save(
            "integration_check", {"connected": True, "checked_at": now()}, "hpc-connection-check"
        )
        result = []
        for row in rows.splitlines():
            fields = row.strip().split("|")
            if len(fields) >= 2 and re.fullmatch(r"\d+", fields[0]):
                result.append((fields[0], fields[1].split()[0].rstrip("+")))
        return result

    def submit(self, identifier: str, initialization: date, actor: str) -> dict:
        script = configured_script()
        if not re.fullmatch(r"[0-9a-f-]{36}", identifier):
            raise ValueError("HPC requests require a UUID identifier")
        name = f"icpac-{identifier}"
        try:
            previous = self.repo.get("hpc_job", identifier)
        except KeyError:
            previous = None
        if previous and previous.get("job_id"):
            return previous
        # Accounting can lag queue visibility. Consult both before submitting.
        found = self._find(name)
        queued = command(["squeue", "--noheader", "--name", name, "--format=%i|%T"])
        for row in queued.splitlines():
            fields = row.split("|")
            if len(fields) == 2 and fields[0].isdigit() and fields[0] not in {r[0] for r in found}:
                found.append((fields[0], fields[1]))
        if len(found) > 1:
            raise RuntimeError("Duplicate HPC job names require operator reconciliation")
        if found:
            job_id, state = found[0]
        else:
            if previous:
                raise RuntimeError(
                    "An uncertain HPC submission requires operator reconciliation; it was not resubmitted"
                )
            payload = {
                "name": name,
                "initialization": initialization.isoformat(),
                "status": "submitting",
                "created_at": now(),
                "created_by": actor,
                "script_sha256": file_checksum(script),
            }
            if not self.repo.insert_once("hpc_job", payload, identifier):
                raise RuntimeError("Another process claimed this HPC submission")
            response = command(
                [
                    "sbatch",
                    "--parsable",
                    "--export=NONE",
                    "--job-name",
                    name,
                    str(script),
                    initialization.isoformat(),
                ]
            )
            job_id = response.split(";")[0]
            if not job_id.isdigit():
                raise RuntimeError(
                    "SLURM did not return a parsable job ID; reconcile before retrying"
                )
            state = "PENDING"
        return self.repo.save(
            "hpc_job",
            {
                "name": name,
                "job_id": job_id,
                "initialization": initialization.isoformat(),
                "status": state,
                "created_by": actor,
                "script_sha256": file_checksum(script),
                "updated_at": now(),
            },
            identifier,
        )

    def poll(self, identifier: str) -> dict:
        configured_script()
        record = self.repo.get("hpc_job", identifier)
        rows = self._find(record["name"])
        match = next((state for job, state in rows if job == record.get("job_id")), None)
        if match:
            record.update(status=match, updated_at=now())
            self.repo.save("hpc_job", record, identifier)
        return record

    def collect(self, identifier: str, actor: str) -> dict:
        """Import only a completed job's receipt and its checksum-checked package."""
        from backend.app.schemas import PackageImportRequest
        from backend.app.services.forecasts import ForecastService

        configured_script()
        record = self.repo.get("hpc_job", identifier)
        if record.get("imported_forecast_id"):
            return record
        if record["status"] != "COMPLETED":
            raise ValueError("Only a completed HPC job can be collected")
        root = Path(os.environ["HPC_RECEIPT_ROOT"]).resolve()
        receipt_path = (root / f"{identifier}.json").resolve()
        if not receipt_path.is_relative_to(root):
            raise ValueError("HPC receipts must stay in their approved directory")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        request = PackageImportRequest(forecast_id=receipt["forecast_id"], actor=actor)
        service = ForecastService(self.platform)
        directory = service.directory(request.forecast_id)
        provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
        if provenance["forecast_initialization"][:10] != record["initialization"]:
            raise ValueError("The HPC output initialization differs from the submitted request")
        if file_checksum(directory / "forecast.nc") != receipt.get("forecast_data_sha256"):
            raise ValueError("The HPC receipt's forecast checksum differs from its package")
        try:
            existing = self.repo.get("forecast_run", request.forecast_id)
        except KeyError:
            existing = service.import_package(request)
        if existing["initialization"][:10] != record["initialization"]:
            raise ValueError("The HPC output initialization differs from the submitted request")
        record.update(imported_forecast_id=request.forecast_id, imported_at=now())
        self.repo.save("hpc_job", record, identifier)
        return record

    def daily(self, actor: str, stamp: datetime | None = None) -> dict:
        """Run from the HPC's own scheduler; never launch overlapping daily jobs."""
        configured_script()
        stamp = stamp or datetime.now(timezone.utc)
        if stamp.tzinfo is None:
            raise ValueError("HPC scheduler timestamps must include a timezone")
        stamp = stamp.astimezone(timezone.utc)
        terminal = {
            "COMPLETED",
            "FAILED",
            "CANCELLED",
            "TIMEOUT",
            "NODE_FAIL",
            "OUT_OF_MEMORY",
            "BOOT_FAIL",
            "DEADLINE",
            "PREEMPTED",
        }
        for record in self.repo.list("hpc_job"):
            if record["status"] not in terminal:
                record = (
                    self.poll(record["id"])
                    if record.get("job_id")
                    else self.submit(
                        record["id"], date.fromisoformat(record["initialization"]), actor
                    )
                )
                if record["status"] not in terminal:
                    return {"status": "waiting", "job": record}
            if record["status"] == "COMPLETED" and not record.get("imported_forecast_id"):
                self.collect(record["id"], actor)
        identifier = str(uuid5(NAMESPACE_URL, f"icpac/hpc/daily/{stamp.date().isoformat()}"))
        return {
            "status": "submitted_or_existing",
            "job": self.submit(identifier, stamp.date(), actor),
        }
