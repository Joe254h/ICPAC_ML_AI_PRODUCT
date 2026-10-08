import re

from fastapi import BackgroundTasks, Depends, FastAPI, Query
from fastapi.responses import Response

from backend.app.schemas import (
    BulletinRequest,
    ChatRequest,
    DescriptorRegisterRequest,
    IndependentTestRequest,
    ReviewRequest,
)
from backend.app.services.bulletin_export import WeeklyHTMLExporter
from backend.app.services.bulletins import WEEKLY, BulletinService, review_label
from backend.app.services.registry import ModelRegistry
from chatbot.providers import warm_up
from chatbot.retrieval import ReferenceIndex
from chatbot.service import Copilot

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def install(app: FastAPI, dependency):
    @app.post("/models/register")
    def register_model(body: DescriptorRegisterRequest, platform=Depends(dependency)) -> dict:
        """Operational models register from a reviewed descriptor."""
        return ModelRegistry(platform).register_descriptor(body.descriptor, body.actor)

    @app.post("/models/{id}/independent-test")
    def independent_test(
        id: str, body: IndependentTestRequest, platform=Depends(dependency)
    ) -> dict:
        return ModelRegistry(platform).record_independent_test(id, body)

    @app.post("/models/{id}/validate")
    def validate_model(id: str, platform=Depends(dependency)) -> dict:
        """Re-verify the model's artifacts and rerun its inference check."""
        return ModelRegistry(platform).validate(id)

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
        """Weekly bulletin drafts (drafts of the retired demonstration are not listed)."""
        return [b for b in reversed(platform.repo.list("bulletin")) if b.get("kind") == WEEKLY]

    @app.post("/bulletins/generate")
    def generate_bulletin(
        body: BulletinRequest, parent_id: str | None = None, platform=Depends(dependency)
    ) -> dict:
        """The weekly bulletin draft of a forecast (the latest by default)."""
        return BulletinService(platform).generate(body.forecast_id, parent_id, body.actor)

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
        """A weekly draft as its frozen Word document (docx) or as a web page (html) with the
        same words and maps."""
        bulletin = platform.repo.get("bulletin", id)
        if bulletin.get("kind") != WEEKLY:
            raise KeyError(id)
        service = BulletinService(platform)
        document = service.released(bulletin)
        name = re.sub(r"[^A-Za-z0-9-]+", "_", bulletin["title"]).strip("_")
        if format == "docx":
            return Response(
                document,
                media_type=DOCX,
                headers={"Content-Disposition": f'attachment; filename="{name}.docx"'},
            )
        label = review_label(bulletin) or bulletin["facts"]["label"]
        content = WeeklyHTMLExporter().export({**bulletin, "id": id, "page_label": label}, document)
        disposition = "inline" if inline else f'attachment; filename="{name}.html"'
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
