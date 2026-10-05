from fastapi import Depends, FastAPI

from backend.app.schemas import Selection
from backend.app.services.jobs import MockJobs


def install(app: FastAPI, dependency):
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
