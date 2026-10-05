import pytest

from backend.app.db import Repository
from backend.app.schemas import ReviewRequest, Selection
from backend.app.services.bulletin_export import HTMLBulletinExporter
from backend.app.services.bulletins import BulletinService, check_consistency
from backend.app.services.platform import Platform


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
