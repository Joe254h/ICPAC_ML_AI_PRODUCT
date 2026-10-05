from fastapi import Depends, FastAPI
from fastapi.responses import Response

from backend.app.schemas import (
    ChatRequest,
    IngestRequest,
    RegisterRequest,
    ReviewRequest,
    Selection,
)
from backend.app.services.bulletin_export import HTMLBulletinExporter
from backend.app.services.bulletins import BulletinService
from backend.app.services.ingestion import ObservationIngestion
from backend.app.services.jobs import Jobs
from backend.app.services.registry import ModelRegistry
from chatbot.retrieval import ReferenceIndex
from chatbot.service import Copilot


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

    @app.post("/chat")
    def chat(body: ChatRequest, platform=Depends(dependency)) -> dict:
        return Copilot(platform).answer(body)

    @app.get("/chat/sessions")
    def sessions(platform=Depends(dependency)) -> list[dict]:
        return [
            {"id": s["id"], "created_at": s["created_at"], "message_count": len(s["messages"])}
            for s in platform.repo.list("chat_session")
        ]

    @app.get("/chat/sessions/{id}")
    def session(id: str, platform=Depends(dependency)) -> dict:
        return platform.repo.get("chat_session", id)

    @app.get("/references/{id}")
    def reference(id: str) -> dict:
        return ReferenceIndex().get(id)

    @app.get("/bulletins")
    def bulletins(platform=Depends(dependency)) -> list[dict]:
        return list(reversed(platform.repo.list("bulletin")))

    @app.post("/bulletins/generate")
    def generate_bulletin(
        body: Selection, parent_id: str | None = None, platform=Depends(dependency)
    ) -> dict:
        return BulletinService(platform).generate(body, parent_id)

    @app.get("/bulletins/compare")
    def compare_bulletins(left: str, right: str, platform=Depends(dependency)) -> dict:
        return BulletinService(platform).compare(left, right)

    @app.get("/bulletins/{id}")
    def bulletin(id: str, platform=Depends(dependency)) -> dict:
        return platform.repo.get("bulletin", id)

    @app.get("/bulletins/{id}/map")
    def bulletin_map(id: str, platform=Depends(dependency)):
        return Response(
            BulletinService(platform).map(platform.repo.get("bulletin", id)), media_type="image/png"
        )

    @app.get("/bulletins/{id}/export")
    def export_bulletin(id: str, platform=Depends(dependency)):
        bulletin = platform.repo.get("bulletin", id)
        content = HTMLBulletinExporter().export(bulletin, BulletinService(platform).map(bulletin))
        return Response(
            content,
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="icpac-bulletin-{id}.html"'},
        )

    @app.post("/bulletins/{id}/{action}")
    def review_bulletin(
        id: str, action: str, body: ReviewRequest, platform=Depends(dependency)
    ) -> dict:
        return BulletinService(platform).transition(id, action, body)

    @app.get("/audit")
    def audit(platform=Depends(dependency)) -> list[dict]:
        return list(reversed(platform.repo.list("audit")))[0:100]
