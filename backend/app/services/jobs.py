from backend.app.schemas import Selection
from hpc.executors import executor


class Jobs:
    def __init__(self, platform):
        self.platform = platform

    def submit(self, selection: Selection, backend: str = "mock_slurm") -> list[dict]:
        return executor(self.platform, backend).submit(selection)

    def list(self) -> list[dict]:
        jobs = self.platform.repo.list("job")
        result = []
        for job in jobs:
            if "dependency" not in job:
                job["dependency"] = None
                if job["status"] in {"queued", "running"}:
                    job.update(
                        status="cancelled",
                        exit_code=130,
                        log="Legacy simulated job retired after executor upgrade; resubmit explicitly.",
                    )
                job = self.platform.repo.save("job", job, job["id"])
            try:
                result.append(executor(self.platform, job["executor"]).status(job))
            except FileNotFoundError as exc:
                result.append({**job, "poll_error": str(exc)})
        return sorted(result, key=lambda row: row["submitted_at"], reverse=True)

    def cancel(self, identifier: str) -> dict:
        job = self.platform.repo.get("job", identifier)
        return executor(self.platform, job["executor"]).cancel(job)
