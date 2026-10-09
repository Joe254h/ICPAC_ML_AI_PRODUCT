import io
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.schemas import ReviewRequest
from backend.app.services import bulletins
from backend.app.services.bulletins import BulletinService, check_consistency
from climate_engine.products.store import PackageStore


class Blobs:
    """In-memory stand-in for the Blob container behind PackageStore."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}

    def upload_blob(self, name, data, *, overwrite=None, **kwargs):
        self.blobs[name] = data

    def list_blobs(self, name_starts_with=None, **kwargs):
        prefix = name_starts_with or ""
        return [SimpleNamespace(name=n) for n in self.blobs if n.startswith(prefix)]

    def download_blob(self, blob, **kwargs):
        return SimpleNamespace(readall=lambda: self.blobs[blob])


# ---------------------------------------------------------------- weekly bulletin drafts

from backend.tests.test_forecasts import env as env  # noqa: E402
from backend.tests.test_forecasts import fast_maps as fast_maps  # noqa: E402
from backend.tests.test_forecasts import run  # noqa: E402


def test_drafts_are_the_weekly_bulletin_of_the_latest_forecast(env, fast_maps, monkeypatch):
    blobs = Blobs()
    monkeypatch.setattr(bulletins, "package_store", lambda: PackageStore(blobs))
    record = run(env)
    client = env.client
    draft = client.post("/bulletins/generate", json={}).json()
    assert draft["kind"] == "icpac-weekly" and draft["forecast_id"] == record["forecast_id"]
    assert draft["title"] == "Weekly Forecast for 12-19 October 2026"
    assert draft["consistency"]["status"] == "PASS"
    assert draft["text"].startswith("Weekly Forecast for 12-19 October 2026\n\nHeadline")
    assert {f"bulletins/{draft['id']}/map.png", f"bulletins/{draft['id']}/bulletin.docx"} <= set(
        blobs.blobs
    )

    word = client.get(f"/bulletins/{draft['id']}/export?format=docx")
    assert word.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "Weekly_Forecast_for_12-19_October_2026.docx" in word.headers["content-disposition"]
    page = client.get(f"/bulletins/{draft['id']}/export?inline=true")
    assert page.headers["content-disposition"] == "inline"
    text = page.text
    # The page carries the draft's words with their bold leads and the document's maps;
    # products still in progress are short notes, not empty maps.
    assert "<h1>Weekly Forecast for 12-19 October 2026</h1>" in text
    assert "<strong>Decision-Support Note:</strong>" in text
    assert "<li><strong>Heavy rainfall (above 200 mm)</strong>" in text
    assert text.count('<figure><img alt="') == 2  # the regional and the Somalia rainfall maps
    assert text.count('<span class="tag">In progress</span>') == 6
    assert "Requires approved climatological 95th-percentile thresholds." in text
    assert "DRAFT - NOT APPROVED" in text and "SYNTHETIC" not in text
    assert 'class="chip draft"' in text and "IGAD Climate Prediction and Applications" in text
    attachment = client.get(f"/bulletins/{draft['id']}/export").headers["content-disposition"]
    assert attachment == 'attachment; filename="Weekly_Forecast_for_12-19_October_2026.html"'

    review = {"actor": "Reviewer", "confirmed": True, "comment": "Checked"}
    assert client.post(f"/bulletins/{draft['id']}/submit", json=review).json()["status"] == (
        "under_review"
    )
    # A reset disk loses the frozen files; review restores them from storage or, without
    # it, by producing them again from the package and matching the recorded checksums.
    shutil.rmtree(Path(draft["document_path"]).parent)
    assert client.post(f"/bulletins/{draft['id']}/approve", json=review).json()["status"] == (
        "approved"
    )
    monkeypatch.setattr(bulletins, "package_store", lambda: None)
    shutil.rmtree(Path(draft["document_path"]).parent)
    approved = client.get(f"/bulletins/{draft['id']}/export?format=docx").content
    # The exported document names the decision in its page header; the reviewed text and
    # maps are the frozen ones.
    assert part(approved, "word/document.xml") == part(word.content, "word/document.xml")
    header = part(approved, "word/header1.xml")
    assert "APPROVED by Reviewer on 20" in header and "DRAFT - NOT APPROVED" not in header
    assert "forecaster review required" not in header
    published = client.post(f"/bulletins/{draft['id']}/publish", json=review).json()
    assert published["status"] == "published"
    page = client.get(f"/bulletins/{draft['id']}/export").text
    assert "PUBLISHED by Reviewer" in page and 'class="chip approved">' in page

    revision = client.post(f"/bulletins/generate?parent_id={draft['id']}", json={}).json()
    assert revision["forecast_id"] == record["forecast_id"]
    assert client.get(f"/bulletins/compare?left={draft['id']}&right={revision['id']}").json()[
        "facts_identical"
    ]


def part(document: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(document)) as archive:
        return archive.read(name).decode("utf-8")


def test_rejected_drafts_and_changed_facts_are_refused(env, fast_maps):
    run(env)
    service = BulletinService(env.platform)
    draft = service.generate(actor="Joe N")
    review = ReviewRequest(actor="Reviewer", confirmed=True, comment="Needs revision")
    with pytest.raises(ValueError, match="status approved"):
        service.transition(draft["id"], "publish", review)
    with pytest.raises(ValueError, match="confirmation"):
        service.transition(draft["id"], "submit", review.model_copy(update={"confirmed": False}))
    service.transition(draft["id"], "submit", review)
    assert service.transition(draft["id"], "reject", review)["status"] == "rejected"
    with pytest.raises(ValueError):
        service.transition(draft["id"], "approve", review)
    assert [
        a["action"] for a in env.platform.repo.list("approval") if a["entity"] == draft["id"]
    ] == [
        "submit",
        "reject",
    ]
    changed = {**draft, "text": "Rainfall is 999999 mm."}
    assert check_consistency(changed)["status"] == "FAIL"
    # Drafts of the retired demonstration stay in old databases but are never listed.
    env.platform.repo.save("bulletin", {"title": "demo", "status": "draft"}, "old-demo")
    # So are weekly drafts made from synthetic test input by earlier versions.
    synthetic = {**draft, "facts": {**draft["facts"], "input": {"synthetic": True}}}
    env.platform.repo.save("bulletin", {**synthetic, "id": "old-synthetic"}, "old-synthetic")
    assert [b["id"] for b in env.client.get("/bulletins").json()] == [draft["id"]]
    assert env.client.get("/bulletins/old-demo/export").status_code == 404
