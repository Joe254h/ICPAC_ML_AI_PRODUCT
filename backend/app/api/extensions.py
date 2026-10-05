from fastapi import Depends, FastAPI

from backend.app.schemas import IngestRequest, Selection
from backend.app.services.ingestion import ObservationIngestion
from backend.app.services.jobs import MockJobs


def install(app: FastAPI, dependency):
    @app.post("/observations/register")
    def register_observations(body: IngestRequest, platform=Depends(dependency)) -> dict:
        return ObservationIngestion(platform).register(body.source, body.path, body.actor)

    @app.get("/jobs")
    def jobs(platform=Depends(dependency)) -> list[dict]:
        return MockJobs(platform).list()

    @app.get("/jobs/{id}")
    def job(id: str, platform=Depends(dependency)) -> dict:
        MockJobs(platform).list()
        return platform.repo.get("job", id)

    @app.post("/jobs")
    def submit(selection: Selection, platform=Depends(dependency)) -> list[dict]:
        return MockJobs(platform).submit(selection)
