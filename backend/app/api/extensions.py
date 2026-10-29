import asyncio
import re

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response

from backend.app.api.access import (
    Principal,
    acting_name,
    chat_slot,
    owned_session,
    principal,
    require_admin,
    require_chat,
    require_operator,
    require_staff_key,
)
from backend.app.db import now
from backend.app.schemas import (
    BulletinEditRequest,
    BulletinRequest,
    BulletinTranslateRequest,
    ChatRequest,
    DescriptorRegisterRequest,
    EmailActionRequest,
    IndependentTestRequest,
    RealtimeReviewRequest,
    ResendRequest,
    ReviewRequest,
    UploadFinishRequest,
    UploadStartRequest,
)
from backend.app.services import bulletin_mail
from backend.app.services.bulletin_export import WeeklyHTMLExporter
from backend.app.services.bulletins import (
    WEEKLY,
    BulletinService,
    RevisionRefused,
    decision_label,
)
from backend.app.services.registry import ModelRegistry
from chatbot.providers import warm_up
from chatbot.retrieval import ReferenceIndex
from chatbot.service import Copilot

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def uploader(purpose: str, authorization: str | None, visitor: str | None) -> Principal:
    """Who may send an upload: a model bundle needs a staff key with the admin role, even on
    the public site; a Copilot file, whoever may use the Copilot."""
    if purpose == "model":
        return require_staff_key(authorization)
    user = principal(authorization, visitor)
    if not user.roles & {"admin", "chat"}:
        raise HTTPException(403, "The chat role is required.")
    return user


def install(app: FastAPI, dependency):
    @app.post("/models/register")
    def register_model(
        body: DescriptorRegisterRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_admin),
    ) -> dict:
        """Operational models register from a reviewed descriptor."""
        return ModelRegistry(platform).register_descriptor(body.descriptor, acting_name(user))

    @app.post("/uploads", status_code=201)
    def start_upload(
        body: UploadStartRequest,
        platform=Depends(dependency),
        authorization: str | None = Header(default=None),
        x_visitor_id: str | None = Header(default=None),
    ) -> dict:
        """Begin a file sent in parts: a model bundle (staff key with the admin role) or a
        file for the Copilot."""
        from backend.app.services.staged_uploads import StagedUploads, UploadError

        user = uploader(body.purpose, authorization, x_visitor_id)
        try:
            return StagedUploads(platform).start(body.purpose, body.name, body.size, user.name)
        except UploadError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/uploads/{id}/parts/{index}")
    async def upload_part(
        id: str,
        index: int,
        request: Request,
        platform=Depends(dependency),
        authorization: str | None = Header(default=None),
        x_visitor_id: str | None = Header(default=None),
    ) -> dict:
        """One numbered part of an upload (the request body), in order from 0."""
        from backend.app.services.staged_uploads import (
            KIND,
            PART_BYTES,
            StagedUploads,
            UploadError,
        )

        try:
            purpose = platform.repo.get(KIND, id)["purpose"]
        except KeyError:
            raise HTTPException(404, "No such upload") from None
        user = uploader(purpose, authorization, x_visitor_id)
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > PART_BYTES:
                raise HTTPException(413, f"A part can be up to {PART_BYTES:,} bytes")
        try:
            return StagedUploads(platform).part(id, index, bytes(data), user.name)
        except UploadError as exc:
            raise HTTPException(422, str(exc)) from None
        except KeyError:
            raise HTTPException(404, "No such upload") from None

    @app.post("/models/upload", status_code=201)
    async def upload_model(
        body: UploadFinishRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_staff_key),
    ) -> dict:
        """Register a model bundle sent in parts: checked like a reviewed descriptor and
        registered as experimental (climate_engine/models/uploads.py)."""
        from backend.app.services.staged_uploads import StagedUploads, UploadError

        try:
            _, data = StagedUploads(platform).finish(body.upload_id, user.name, "model")
            return await asyncio.to_thread(ModelRegistry(platform).register_upload, data, user.name)
        except KeyError:
            raise HTTPException(404, "No such upload") from None
        except (UploadError, ValueError, FileNotFoundError) as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/models/{id}/independent-test")
    def independent_test(
        id: str,
        body: IndependentTestRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_admin),
    ) -> dict:
        return ModelRegistry(platform).record_independent_test(
            id, body.model_copy(update={"actor": acting_name(user, body.actor)})
        )

    @app.post("/models/{id}/realtime-review")
    def realtime_review(
        id: str,
        body: RealtimeReviewRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_admin),
    ) -> dict:
        """Confirm, or withdraw, that a real-time input source matches the frozen model."""
        if not body.withdraw and not body.forecast_id:
            raise HTTPException(422, "Name the forecast run whose input checks all passed")
        return ModelRegistry(platform).review_realtime_feed(
            id, body.model_copy(update={"actor": acting_name(user, body.actor)})
        )

    @app.post("/models/{id}/validate")
    def validate_model(
        id: str, platform=Depends(dependency), user: Principal = Depends(require_admin)
    ) -> dict:
        """Re-verify the model's artifacts and rerun its inference check."""
        return ModelRegistry(platform).validate(id, acting_name(user))

    @app.post("/models/{id}/{action}")
    def model_action(
        id: str,
        action: str,
        body: ReviewRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_admin),
    ) -> dict:
        return ModelRegistry(platform).transition(
            id, action, body.model_copy(update={"actor": acting_name(user, body.actor)})
        )

    @app.post("/chat", dependencies=[Depends(chat_slot)])
    def chat(
        body: ChatRequest, platform=Depends(dependency), user: Principal = Depends(require_chat)
    ) -> dict:
        if body.session_id:
            session = owned_session(platform.repo, body.session_id, user)
            if len(session["messages"]) >= 100:
                raise HTTPException(422, "Start a new conversation after 50 questions.")
        platform.repo.chat_allowance(user.name)
        return Copilot(platform).answer(body, owner=user.name, actor=acting_name(user, body.actor))

    @app.post("/chat/attachments", status_code=201)
    async def attach(
        request: Request,
        name: str = Query(min_length=1, max_length=200),
        platform=Depends(dependency),
        user: Principal = Depends(require_chat),
    ) -> dict:
        """A file for the next question (the request body): any format, read as far as it
        can be; only its owner can use it."""
        from chatbot.attachments import MAX_BYTES, AttachmentError, Attachments

        limit = f"Files can be up to {MAX_BYTES // 1024**2} MB"
        if int(request.headers.get("content-length") or 0) > MAX_BYTES:
            raise HTTPException(413, limit)
        data = bytearray()
        async for chunk in request.stream():
            data += chunk
            if len(data) > MAX_BYTES:
                raise HTTPException(413, limit)
        try:
            return await asyncio.to_thread(Attachments(platform).save, name, bytes(data), user.name)
        except AttachmentError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/chat/attachments/staged", status_code=201)
    async def attach_staged(
        body: UploadFinishRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_chat),
    ) -> dict:
        """A file for the next question that arrived in parts (larger than one request)."""
        from backend.app.services.staged_uploads import StagedUploads, UploadError
        from chatbot.attachments import AttachmentError, Attachments

        try:
            name, data = StagedUploads(platform).finish(body.upload_id, user.name, "attachment")
            return await asyncio.to_thread(Attachments(platform).save, name, data, user.name)
        except KeyError:
            raise HTTPException(404, "No such upload") from None
        except (UploadError, AttachmentError) as exc:
            raise HTTPException(422, str(exc)) from None

    def first_question(session: dict) -> str:
        """Older conversations have no title: name them by their first question."""
        asked = next((m.get("text") for m in session["messages"] if m.get("role") == "user"), "")
        return " ".join(str(asked or "").split())[:80]

    @app.get("/chat/sessions")
    def sessions(
        background: BackgroundTasks,
        archived: bool = False,
        platform=Depends(dependency),
        user: Principal = Depends(require_chat),
    ) -> list[dict]:
        """Conversations, newest first: the open ones, or with ``archived`` the archived."""
        # The Copilot page lists sessions when it opens: wake a model that scaled to zero.
        background.add_task(warm_up)
        return [
            {
                "id": s["id"],
                "title": s.get("title") or first_question(s) or "Conversation",
                "created_at": s["created_at"],
                "updated_at": s.get("updated_at", s["created_at"]),
                "message_count": len(s["messages"]),
                "context": s.get("context"),
                "archived": bool(s.get("archived_at")),
            }
            for s in sorted(
                platform.repo.list("chat_session"),
                key=lambda s: s.get("updated_at", s["created_at"]),
                reverse=True,
            )
            if bool(s.get("archived_at")) == archived and s.get("owner") == user.name
        ]

    @app.get("/chat/sessions/{id}")
    def session(
        id: str, platform=Depends(dependency), user: Principal = Depends(require_chat)
    ) -> dict:
        return owned_session(platform.repo, id, user)

    @app.post("/chat/sessions/{id}/archive")
    def archive_session(
        id: str,
        archived: bool = True,
        platform=Depends(dependency),
        user: Principal = Depends(require_chat),
    ) -> dict:
        """Archive a conversation (out of the list, kept), or bring it back."""
        record = owned_session(platform.repo, id, user)
        record["archived_at"] = now() if archived else None
        return platform.repo.save("chat_session", record, id)

    @app.delete("/chat/sessions/{id}", status_code=204)
    def delete_session(
        id: str, platform=Depends(dependency), user: Principal = Depends(require_chat)
    ) -> Response:
        """Delete a conversation and its messages for good."""
        owned_session(platform.repo, id, user)
        platform.repo.delete("chat_session", id)
        return Response(status_code=204)

    @app.get("/references/{id}")
    def reference(id: str) -> dict:
        return ReferenceIndex().get(id)

    @app.get("/bulletins")
    def bulletins(platform=Depends(dependency)) -> list[dict]:
        """Weekly bulletin drafts of real forecasts. Drafts of the retired demonstration and
        of synthetic test input stay in older databases but are not listed."""
        return [
            b
            for b in reversed(platform.repo.list("bulletin"))
            if b.get("kind") == WEEKLY
            and not ((b.get("facts") or {}).get("input") or {}).get("synthetic")
        ]

    @app.post("/bulletins/generate")
    def generate_bulletin(
        body: BulletinRequest,
        parent_id: str | None = None,
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> dict:
        """The weekly bulletin draft of a forecast (the latest by default)."""
        return BulletinService(platform).generate(body.forecast_id, parent_id, acting_name(user))

    @app.get("/bulletins/email-status")
    def bulletin_email_status() -> dict:
        """Whether review emails go out, and to how many reviewers, publishers, readers."""
        return bulletin_mail.email_status()

    @app.get("/bulletins/email-action")
    def describe_email_action(token: str, platform=Depends(dependency)) -> dict:
        """What an emailed link allows; opening it changes nothing."""
        return bulletin_mail.describe_link(platform, token)

    @app.post("/bulletins/email-action")
    def email_action(body: EmailActionRequest, platform=Depends(dependency)) -> dict:
        """Approve, reject or publish from an emailed link, as the person it was sent to."""
        return bulletin_mail.act_on_link(
            platform, body.token, body.decision, body.name, body.comment
        )

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
        label = decision_label(bulletin) or bulletin["facts"]["label"]
        content = WeeklyHTMLExporter().export({**bulletin, "id": id, "page_label": label}, document)
        disposition = "inline" if inline else f'attachment; filename="{name}.html"'
        return Response(
            content, media_type="text/html", headers={"Content-Disposition": disposition}
        )

    @app.post("/bulletins/{id}/edit")
    def edit_bulletin(
        id: str,
        body: BulletinEditRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> dict:
        """A new version of a draft with the forecaster's own wording."""
        try:
            return BulletinService(platform).edit(
                id,
                body.model_dump(exclude={"actor"}),
                acting_name(user, body.actor),
            )
        except RevisionRefused as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/bulletins/{id}/translate")
    def translate_bulletin(
        id: str,
        body: BulletinTranslateRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> dict:
        """A new version of a draft in another language, every figure checked."""
        try:
            return BulletinService(platform).translate(
                id, body.language, acting_name(user, body.actor)
            )
        except RevisionRefused as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/bulletins/{id}/resend")
    def resend_bulletin_email(
        id: str,
        body: ResendRequest,
        platform=Depends(dependency),
        user: Principal = Depends(require_operator),
    ) -> dict:
        """Send the email of the bulletin's current step again (new links)."""
        bulletin = platform.repo.get("bulletin", id)
        platform.repo.audit(
            "bulletin_email_resent", acting_name(user), id, {"status": bulletin["status"]}
        )
        return bulletin_mail.notify(platform, bulletin)

    @app.post("/bulletins/{id}/{action}")
    def review_bulletin(
        id: str,
        action: str,
        body: ReviewRequest,
        platform=Depends(dependency),
        user: Principal = Depends(principal),
    ) -> dict:
        role = (
            "publisher"
            if action == "publish"
            else "reviewer"
            if action in {"approve", "reject"}
            else "operator"
        )
        if "admin" not in user.roles and role not in user.roles:
            raise HTTPException(403, f"The {role} role is required.")
        return BulletinService(platform).transition(
            id, action, body.model_copy(update={"actor": acting_name(user, body.actor)})
        )

    @app.get("/audit")
    def audit(platform=Depends(dependency), user: Principal = Depends(require_admin)) -> list[dict]:
        return list(reversed(platform.repo.list("audit")))[0:100]

    @app.get("/access/me")
    def me(user: Principal = Depends(principal)) -> dict:
        return {"name": user.name, "roles": sorted(user.roles)}
