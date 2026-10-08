import io
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.app.db import Repository
from backend.app.schemas import ReviewRequest, Selection
from backend.app.services import bulletins
from backend.app.services.bulletin_export import HTMLBulletinExporter
from backend.app.services.bulletins import BulletinService, check_consistency
from backend.app.services.platform import Platform
from climate_engine.products.store import PackageStore


def test_bulletin_requires_review_and_preserves_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    service = BulletinService(platform)
    bulletin = service.generate(Selection(country="Kenya"))
    review = ReviewRequest(
        actor="Reviewer", confirmed=True, comment="Checked sources, QC and units"
    )
    with pytest.raises(ValueError, match="status approved"):
        service.transition(bulletin["id"], "publish", review)
    with pytest.raises(ValueError, match="confirmation"):
        service.transition(bulletin["id"], "submit", review.model_copy(update={"confirmed": False}))
    service.transition(bulletin["id"], "submit", review)
    approved = service.transition(bulletin["id"], "approve", review)
    assert approved["facts_checksum"] == bulletin["facts_checksum"]
    published = service.transition(bulletin["id"], "publish", review)
    assert published["status"] == "published"
    assert len(platform.repo.list("approval")) == 3
    output = HTMLBulletinExporter().export(published, service.map(published))
    assert b"data:image/png;base64," in output
    assert b"NOT FOR OPERATIONAL USE" in output
    changed = {**bulletin, "text": "Rainfall is 999999 mm."}
    assert check_consistency(changed)["status"] == "FAIL"


def test_rejected_draft_and_comparison(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    service = BulletinService(platform)
    a = service.generate(Selection(country="Kenya"))
    b = service.generate(Selection(country="Somalia"), a["id"])
    assert service.compare(a["id"], b["id"])["changed_selection"] == ["country"]
    review = ReviewRequest(actor="Reviewer", confirmed=True, comment="Needs revision")
    service.transition(a["id"], "submit", review)
    assert service.transition(a["id"], "reject", review)["status"] == "rejected"
    with pytest.raises(ValueError):
        service.transition(a["id"], "approve", review)


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


def test_frozen_map_survives_a_reset_disk(tmp_path, monkeypatch):
    """A restarted container loses RUN_ROOT; review must still find the same frozen map."""
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    blobs = Blobs()
    monkeypatch.setattr(bulletins, "package_store", lambda: PackageStore(blobs))
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    service = BulletinService(platform)
    draft = service.generate(Selection(country="Kenya"))
    assert f"bulletins/{draft['id']}/map.png" in blobs.blobs
    shutil.rmtree(tmp_path / "runs")
    review = ReviewRequest(actor="Reviewer", confirmed=True, comment="Checked")
    assert service.transition(draft["id"], "submit", review)["status"] == "under_review"
    assert Path(draft["map_path"]).is_file()

    # Without a store, the map is rendered again from the frozen selection and accepted
    # only when it is byte-identical; a different image never replaces the frozen one.
    monkeypatch.setattr(bulletins, "package_store", lambda: None)
    shutil.rmtree(tmp_path / "runs")
    assert service.map(platform.repo.get("bulletin", draft["id"]))[:4] == bytes([137, 80, 78, 71])
    shutil.rmtree(tmp_path / "runs")
    monkeypatch.setattr(platform, "png", lambda selection: b"another image")
    with pytest.raises(FileNotFoundError, match="Generate a new draft"):
        service.transition(draft["id"], "approve", review)


def test_drafts_keep_every_sentence_when_the_language_model_drops_some(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")

    def endpoint(url, **kwargs):
        content = '{"sentence_ids":["forecast"]}'
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": content}}]},
        )

    monkeypatch.setattr(httpx, "post", endpoint)
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    draft = BulletinService(platform).generate(Selection(country="Kenya"))
    assert draft["sentence_ids"][0] == "forecast"
    assert set(draft["sentence_ids"]) == set(draft["sentences"])
    assert check_consistency(draft)["status"] == "PASS"


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
    # The page is the Word document: its title, bold leads, bullets and every picture.
    assert "Weekly Forecast for 12-19 October 2026" in text
    assert "<strong>Decision-Support Note:</strong>" in text
    assert "<li><strong>Heavy rainfall (above 200 mm)</strong>" in text
    assert "95</strong><strong><sup>th</sup></strong>" in text
    assert text.count("data:image/png;base64,") == 7 and text.count("data:image/gif") == 1
    assert "DRAFT - NOT APPROVED" in text and "SYNTHETIC TEST INPUT" in text

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
    assert "forecaster review required" not in header and "SYNTHETIC TEST INPUT" in header
    published = client.post(f"/bulletins/{draft['id']}/publish", json=review).json()
    assert published["status"] == "published"
    page = client.get(f"/bulletins/{draft['id']}/export").text
    assert "PUBLISHED (local demonstration record) by Reviewer" in page

    revision = client.post(f"/bulletins/generate?parent_id={draft['id']}", json={}).json()
    assert revision["forecast_id"] == record["forecast_id"]
    assert client.get(f"/bulletins/compare?left={draft['id']}&right={revision['id']}").json()[
        "facts_identical"
    ]


def part(document: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(document)) as archive:
        return archive.read(name).decode("utf-8")


def test_demonstration_drafts_have_no_word_document(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    draft = BulletinService(platform).generate(Selection(country="Kenya"))
    assert "kind" not in draft
    with pytest.raises(ValueError, match="Only weekly"):
        BulletinService(platform).document(draft)
