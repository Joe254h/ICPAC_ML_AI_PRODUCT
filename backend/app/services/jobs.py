from datetime import datetime, timedelta, timezone

from backend.app.db import now
from backend.app.schemas import Selection

STAGES = ["download", "qc", "preprocess", "features", "inference", "verification", "products"]


class MockJobs:
    def __init__(self, platform):
        self.platform = platform

    def submit(self, selection: Selection, executor: str = "mock_slurm") -> list[dict]:
        group = self.platform.repo.save(
            "job_group", {"cycle": selection.cycle, "created_at": now()}
        )
        jobs = []
        for index, stage in enumerate(STAGES):
            jobs.append(
                self.platform.repo.save(
                    "job",
                    {
                        "cycle": selection.cycle,
                        "stage": stage,
                        "executor": executor,
                        "status": "queued",
                        "index": index,
                        "group_id": group["id"],
                        "submitted_at": now(),
                        "start_time": None,
                        "end_time": None,
                        "exit_code": None,
                        "log_path": None,
                        "user": "prototype",
                        "log": "SIMULATED JOB: awaiting afterok dependency.",
                        "selection": selection.model_dump(),
                    },
                )
            )
        self.platform.repo.audit("submit_demo_pipeline", "prototype", group["id"])
        return jobs

    def list(self) -> list[dict]:
        jobs = self.platform.repo.list("job")
        for job in jobs:
            if job["status"] in {"failed", "cancelled"}:
                continue
            age = (
                datetime.now(timezone.utc) - datetime.fromisoformat(job["submitted_at"])
            ).total_seconds()
            start_after = job["index"] * 2
            if age >= start_after + 2:
                job.update(
                    status="success",
                    exit_code=0,
                    start_time=(
                        datetime.fromisoformat(job["submitted_at"]) + timedelta(seconds=start_after)
                    ).isoformat(),
                    end_time=(
                        datetime.fromisoformat(job["submitted_at"])
                        + timedelta(seconds=start_after + 2)
                    ).isoformat(),
                    log=f"SIMULATED {job['stage']} completed. No external data download or SLURM submission.",
                )
            elif age >= start_after:
                job.update(
                    status="running", start_time=now(), log=f"SIMULATED {job['stage']} running."
                )
            self.platform.repo.save("job", job, job["id"])
        return sorted(jobs, key=lambda j: j["submitted_at"], reverse=True)
