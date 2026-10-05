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
            try:
                result.append(executor(self.platform, job["executor"]).status(job))
            except FileNotFoundError as exc:
                result.append({**job, "poll_error": str(exc)})
        return sorted(result, key=lambda row: row["submitted_at"], reverse=True)

    def cancel(self, identifier: str) -> dict:
        job = self.platform.repo.get("job", identifier)
        return executor(self.platform, job["executor"]).cancel(job)
