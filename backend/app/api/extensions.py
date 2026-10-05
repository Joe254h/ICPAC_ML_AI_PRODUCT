from fastapi import Depends, FastAPI

from backend.app.schemas import IngestRequest, RegisterRequest, ReviewRequest, Selection
from backend.app.services.ingestion import ObservationIngestion
from backend.app.services.jobs import Jobs
from backend.app.services.registry import ModelRegistry


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

    @app.post("/models/register")
    def register_model(body: RegisterRequest, platform=Depends(dependency)) -> dict:
        return ModelRegistry(platform).register(body)

    @app.post("/models/{id}/validate")
    def validate_model(id: str, body: Selection, platform=Depends(dependency)) -> dict:
        return ModelRegistry(platform).validate(id, body)

    @app.post("/models/{id}/{action}")
    def model_action(
        id: str, action: str, body: ReviewRequest, platform=Depends(dependency)
    ) -> dict:
        return ModelRegistry(platform).transition(id, action, body)
