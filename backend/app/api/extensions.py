import re

from fastapi import BackgroundTasks, Depends, FastAPI, Query
from fastapi.responses import Response

from backend.app.schemas import (
    ChatRequest,
    DescriptorRegisterRequest,
    IndependentTestRequest,
    IngestRequest,
    RegisterRequest,
    ReviewRequest,
    Selection,
)
from backend.app.services.bulletin_export import HTMLBulletinExporter, WeeklyHTMLExporter
from backend.app.services.bulletins import WEEKLY, BulletinService
from backend.app.services.ingestion import ObservationIngestion
from backend.app.services.jobs import Jobs
from backend.app.services.registry import ModelRegistry
from chatbot.providers import warm_up
from chatbot.retrieval import ReferenceIndex
from chatbot.service import Copilot

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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
    def register_model(
        body: DescriptorRegisterRequest | RegisterRequest, platform=Depends(dependency)
    ) -> dict:
        """Operational models register from a reviewed descriptor; demo models directly."""
        if isinstance(body, DescriptorRegisterRequest):
            return ModelRegistry(platform).register_descriptor(body.descriptor, body.actor)
        return ModelRegistry(platform).register(body)

    @app.post("/models/{id}/independent-test")
    def independent_test(
        id: str, body: IndependentTestRequest, platform=Depends(dependency)
    ) -> dict:
        return ModelRegistry(platform).record_independent_test(id, body)

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
    def sessions(background: BackgroundTasks, platform=Depends(dependency)) -> list[dict]:
        # The Copilot page lists sessions when it opens: wake a model that scaled to zero.
        background.add_task(warm_up)
        return [
            {
                "id": s["id"],
                "title": s.get("title", "Forecast conversation"),
                "created_at": s["created_at"],
                "updated_at": s.get("updated_at", s["created_at"]),
                "message_count": len(s["messages"]),
                "context": s.get("context"),
            }
            for s in sorted(
                platform.repo.list("chat_session"),
                key=lambda s: s.get("updated_at", s["created_at"]),
                reverse=True,
            )
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
        body: Selection,
        parent_id: str | None = None,
        forecast_id: str | None = Query(None, pattern=r"^w2-\d{4}-\d{2}-\d{2}-[0-9a-f]{8}$"),
        platform=Depends(dependency),
    ) -> dict:
        """The weekly bulletin of a forecast (the latest by default); before the first
        forecast, a demonstration summary of the selection."""
        return BulletinService(platform).generate(body, parent_id, forecast_id)

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
    def export_bulletin(
        id: str,
        format: str = Query("html", pattern=r"^(html|docx)$"),
        inline: bool = False,
        platform=Depends(dependency),
    ):
        """A weekly draft as its frozen Word document (docx) or that document as a web page
        (html); a demonstration draft as its HTML summary."""
        bulletin = platform.repo.get("bulletin", id)
        service = BulletinService(platform)
        if bulletin.get("kind") == WEEKLY:
            document = service.released(bulletin)
            if format == "docx":
                name = re.sub(r"[^A-Za-z0-9-]+", "_", bulletin["title"]).strip("_")
                return Response(
                    document,
                    media_type=DOCX,
                    headers={"Content-Disposition": f'attachment; filename="{name}.docx"'},
                )
            content = WeeklyHTMLExporter().export({**bulletin, "id": id}, document)
        elif format == "docx":
            raise ValueError("Demonstration drafts have no Word document")
        else:
            content = HTMLBulletinExporter().export(bulletin, service.map(bulletin))
        disposition = "inline" if inline else f'attachment; filename="icpac-bulletin-{id}.html"'
        return Response(
            content, media_type="text/html", headers={"Content-Disposition": disposition}
        )

    @app.post("/bulletins/{id}/{action}")
    def review_bulletin(
        id: str, action: str, body: ReviewRequest, platform=Depends(dependency)
    ) -> dict:
        return BulletinService(platform).transition(id, action, body)

    @app.get("/audit")
    def audit(platform=Depends(dependency)) -> list[dict]:
        return list(reversed(platform.repo.list("audit")))[0:100]
