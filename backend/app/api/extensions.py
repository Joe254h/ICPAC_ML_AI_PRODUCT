from fastapi import Depends, FastAPI

from backend.app.schemas import IngestRequest, Selection
from backend.app.services.ingestion import ObservationIngestion
from backend.app.services.jobs import Jobs


def install(app: FastAPI, dependency):
    @app.post("/observations/register")
    def register_observations(body: IngestRequest, platform=Depends(dependency)) -> dict:
        return ObservationIngestion(platform).register(body.source, body.path, body.actor)

    @app.get("/jobs")
    def jobs(platform=Depends(dependency)) -> list[dict]:
        return Jobs(platform).list()

    @app.get("/jobs/{id}")
    def job(id: str, platform=Depends(dependency)) -> dict:
        Jobs(platform).list()
        return platform.repo.get("job", id)

    @app.post("/jobs")
    def submit(
        selection: Selection, executor: str = "mock_slurm", platform=Depends(dependency)
    ) -> list[dict]:
        return Jobs(platform).submit(selection, executor)

    @app.get("/jobs/{id}/logs")
    def logs(id: str, platform=Depends(dependency)) -> dict:
        Jobs(platform).list()
        return {"log": platform.repo.get("job", id)["log"]}

    @app.post("/jobs/{id}/cancel")
    def cancel_job(id: str, platform=Depends(dependency)) -> dict:
        return Jobs(platform).cancel(id)
