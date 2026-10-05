"""Allowlisted execution; no user-provided command strings."""

import os
import re
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path

from backend.app.db import now
from climate_engine.core import ROOT
from hpc.pipeline import STAGES, run_stage

TERMINAL = {"success", "failed", "cancelled", "blocked"}
LOCAL_QUEUE = threading.Lock()
logger = logging.getLogger("icpac.jobs")


class JobExecutor(ABC):
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    @abstractmethod
    def submit(self, selection) -> list[dict]: ...

    @abstractmethod
    def status(self, job: dict) -> dict: ...

    def logs(self, job: dict) -> str:
        return self.status(job)["log"]

    def cancel(self, job: dict) -> dict:
        if job["status"] in TERMINAL:
            raise ValueError("Completed jobs cannot be cancelled")
        for member in self.repo.list("job"):
            if member["group_id"] == job["group_id"] and member["status"] not in TERMINAL:
                member.update(
                    status="cancelled",
                    end_time=now(),
                    exit_code=130,
                    log=member["log"] + "\nCancellation requested.",
                )
                self.repo.save("job", member, member["id"])
        self.repo.audit("cancel_pipeline", "prototype", job["group_id"])
        return self.repo.get("job", job["id"])

    def create(self, selection, name: str) -> list[dict]:
        group = self.repo.save(
            "job_group",
            {"selection": selection.model_dump(), "executor": name, "created_at": now()},
        )
        jobs: list[dict] = []
        for index, stage in enumerate(STAGES):
            jobs.append(
                self.repo.save(
                    "job",
                    {
                        "cycle": selection.cycle,
                        "selection": selection.model_dump(),
                        "stage": stage,
                        "index": index,
                        "executor": name,
                        "group_id": group["id"],
                        "dependency": jobs[-1]["id"] if jobs else None,
                        "status": "queued",
                        "submitted_at": now(),
                        "start_time": None,
                        "end_time": None,
                        "exit_code": None,
                        "log_path": None,
                        "user": "prototype",
                        "log": "Awaiting afterok dependency.",
                    },
                )
            )
        self.repo.audit("submit_pipeline", "prototype", group["id"], {"executor": name})
        return jobs


class LocalExecutor(JobExecutor):
    def submit(self, selection) -> list[dict]:
        jobs = self.create(selection, "local")
        threading.Thread(target=self._run, args=(jobs, selection), daemon=True).start()
        return jobs

    def _run(self, jobs: list[dict], selection) -> None:
        # Bound this prototype to one CPU pipeline at a time.
        with LOCAL_QUEUE:
            for item in jobs:
                job = self.repo.get("job", item["id"])
                if job["status"] == "cancelled":
                    continue
                if job["dependency"]:
                    dependency = self.repo.get("job", job["dependency"])
                    if dependency["status"] != "success":
                        job.update(
                            status="blocked",
                            end_time=now(),
                            log="Dependency did not succeed; stage not executed.",
                        )
                        self.repo.save("job", job, job["id"])
                        continue
                job.update(status="running", start_time=now(), log="Fixed local stage running.")
                self.repo.save("job", job, job["id"])
                try:
                    logger.info(
                        "stage_started",
                        extra={
                            "run_id": job["group_id"],
                            "job": job["id"],
                            "stage": job["stage"],
                            "cycle": selection.cycle,
                            "model": selection.model,
                            "dataset": selection.observation,
                        },
                    )
                    log = run_stage(self.platform, selection, job["stage"], job["group_id"])
                    job.update(status="success", exit_code=0, log=log)
                except Exception as exc:
                    job.update(status="failed", exit_code=1, log=f"{type(exc).__name__}: {exc}")
                    logger.error(
                        "stage_failed",
                        extra={"run_id": job["group_id"], "job": job["id"], "stage": job["stage"]},
                    )
                if self.repo.get("job", job["id"])["status"] != "cancelled":
                    job["end_time"] = now()
                    self.repo.save("job", job, job["id"])

    def status(self, job: dict) -> dict:
        return self.repo.get("job", job["id"])


class MockSlurmExecutor(JobExecutor):
    def submit(self, selection) -> list[dict]:
        return self.create(selection, "mock_slurm")

    def status(self, job: dict) -> dict:
        job = self.repo.get("job", job["id"])
        if job["status"] in TERMINAL:
            return job
        if job["dependency"]:
            previous = self.status(self.repo.get("job", job["dependency"]))
            if previous["status"] in {"failed", "cancelled", "blocked"}:
                job.update(
                    status="blocked", end_time=now(), log="SIMULATED: afterok dependency failed."
                )
            elif previous["status"] != "success":
                return job
        if job["status"] == "blocked":
            return self.repo.save("job", job, job["id"])
        if job["status"] == "queued":
            job.update(
                status="running",
                start_time=now(),
                mock_started=time.time(),
                log="SIMULATED stage running; no cluster submission.",
            )
        elif time.time() - job["mock_started"] >= 1:
            job.update(
                status="success",
                end_time=now(),
                exit_code=0,
                log="SIMULATED stage completed; no scientific products created.",
            )
        return self.repo.save("job", job, job["id"])


class SlurmExecutor(JobExecutor):
    def command(self, argv: list[str]) -> str:
        if os.getenv("ENABLE_SLURM") != "true":
            raise FileNotFoundError(
                "SLURM disabled; set ENABLE_SLURM=true on the configured cluster host"
            )
        try:
            return subprocess.run(
                argv, cwd=ROOT, capture_output=True, text=True, check=True, timeout=20
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise FileNotFoundError(
                "SLURM command unavailable or unsuccessful; inspect operator logs"
            ) from exc

    def submit(self, selection) -> list[dict]:
        # Check the opt-in before creating records or writing the job request.
        self.command(["sinfo", "--noheader", "--format=%P"])
        jobs = self.create(selection, "slurm")
        output = Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs"))) / jobs[0]["group_id"]
        output.mkdir(parents=True, exist_ok=True)
        selection_path = output / "selection.json"
        selection_path.write_text(selection.model_dump_json(), encoding="utf-8")
        previous = None
        try:
            for job in jobs:
                log = output / f"{job['stage']}.log"
                argv = ["sbatch", "--parsable", "--output", str(log), "--error", str(log)]
                if previous:
                    argv.extend([f"--dependency=afterok:{previous}", "--kill-on-invalid-dep=yes"])
                argv.extend(
                    [
                        str(ROOT / "hpc" / "templates" / "stage.slurm"),
                        str(selection_path),
                        job["stage"],
                        job["group_id"],
                    ]
                )
                identifier = self.command(argv).split(";")[0]
                if not re.fullmatch(r"[0-9]+", identifier):
                    raise ValueError("Unexpected SLURM job identifier")
                previous = identifier
                job.update(
                    slurm_id=identifier,
                    log_path=str(log),
                    log="Submitted fixed cluster stage with afterok dependency.",
                )
                self.repo.save("job", job, job["id"])
        except Exception:
            for job in jobs:
                if job.get("slurm_id"):
                    try:
                        self.command(["scancel", job["slurm_id"]])
                    except FileNotFoundError:
                        pass
                job.update(
                    status="failed",
                    end_time=now(),
                    exit_code=1,
                    log="Partial submission failed; cancellation attempted for submitted stages.",
                )
                self.repo.save("job", job, job["id"])
            raise
        return jobs

    def status(self, job: dict) -> dict:
        if job["status"] in TERMINAL or not job.get("slurm_id"):
            return job
        raw = self.command(
            [
                "sacct",
                "-j",
                job["slurm_id"],
                "--noheader",
                "--parsable2",
                "--format=JobIDRaw,State,Start,End,ExitCode",
            ]
        )
        for row in raw.splitlines():
            cells = row.split("|")
            if len(cells) < 5 or cells[0] != job["slurm_id"]:
                continue
            state = cells[1].split()[0]
            status = {
                "COMPLETED": "success",
                "RUNNING": "running",
                "PENDING": "queued",
                "CONFIGURING": "queued",
                "COMPLETING": "running",
                "SUSPENDED": "running",
                "REQUEUED": "queued",
                "CANCELLED": "cancelled",
            }.get(state, "failed")
            job.update(
                status=status,
                start_time=cells[2],
                end_time=cells[3],
                exit_code=int(cells[4].split(":")[0]),
            )
        log = Path(job["log_path"])
        if log.is_file():
            with log.open("rb") as stream:
                stream.seek(max(0, log.stat().st_size - 64000))
                job["log"] = stream.read().decode("utf-8", errors="replace")
        return self.repo.save("job", job, job["id"])

    def cancel(self, job: dict) -> dict:
        for member in self.repo.list("job"):
            if member["group_id"] == job["group_id"] and member.get("slurm_id"):
                self.command(["scancel", member["slurm_id"]])
        return super().cancel(job)


def executor(platform, name: str) -> JobExecutor:
    implementations: dict[str, type[JobExecutor]] = {
        "local": LocalExecutor,
        "mock_slurm": MockSlurmExecutor,
        "slurm": SlurmExecutor,
    }
    if name not in implementations:
        raise ValueError("Unknown executor")
    return implementations[name](platform)
