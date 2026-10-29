"""Model bundles uploaded through the website in parts, and large Copilot files.

The refit bundle is uploaded again under another policy (MBC only), so it is a new model
artifact claim on the real authoritative grid. Uploads need a staff key with the admin
role even on the public site; a bundle that fails a check leaves nothing behind.
"""

import io
import shutil
import zipfile
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services import operational
from backend.app.services.staged_uploads import PART_BYTES
from climate_engine.core import ROOT
from climate_engine.models import uploads

KEY = "test-bulletin-operator-key-00000000"
STAFF = {"Authorization": f"Bearer {KEY}"}
VISITOR = {"X-Visitor-Id": "0123456789abcdef0123456789abcdef"}
BUNDLE = ROOT / "artifacts" / "bundles" / "ICPAC_WEEK2_CATBOOST_FINAL_REFIT_2005_2021"
EVIDENCE = "verification/FINAL_REFIT_RETROSPECTIVE_2022_2024_20261027/tables/GLOBAL_METRICS.csv"


def bundle(model_id: str = "uploaded_refit_mbc_only", **changes) -> bytes:
    """The refit bundle as a ZIP: its descriptor at the top, the bundle in a folder."""
    data = yaml.safe_load(
        (ROOT / "config/model_registry/icpac_week2_catboost_refit_v1.yaml").read_text()
    )
    prefix = f"bundles/{BUNDLE.name}/"
    data.update(
        model_id=model_id,
        policy="mbc_only",
        artifacts={k: v.replace(prefix, "bundle/") for k, v in data["artifacts"].items()},
        **changes,
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("registration.yaml", yaml.safe_dump(data))
        for path in BUNDLE.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, "bundle/" + path.relative_to(BUNDLE).as_posix())
        archive.write(ROOT / "artifacts" / EVIDENCE, EVIDENCE)
    return buffer.getvalue()


class Store:
    """The part of the Blob Storage package store an upload uses."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}

    def put(self, name, data):
        self.blobs[name] = data

    def get(self, name):
        return self.blobs.get(name)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BULLETIN_OPERATOR_KEY", KEY)
    monkeypatch.setenv("ACCESS_MODE", "public")
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("MODEL_UPLOAD_ROOT", str(tmp_path / "uploads"))
    store = Store()
    monkeypatch.setattr("climate_engine.products.store.package_store", lambda: store)
    operational._models.clear()
    app = create_app(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, platform=app.state.platform, store=store)


def send(client, data: bytes, purpose: str, name: str, headers: dict) -> str:
    started = client.post(
        "/uploads", json={"purpose": purpose, "name": name, "size": len(data)}, headers=headers
    )
    assert started.status_code == 201, started.text
    upload = started.json()
    assert upload["part_bytes"] == PART_BYTES
    for index, offset in enumerate(range(0, len(data), PART_BYTES)):
        part = client.post(
            f"/uploads/{upload['id']}/parts/{index}",
            content=data[offset : offset + PART_BYTES],
            headers={**headers, "Content-Type": "application/octet-stream"},
        )
        assert part.status_code == 200, part.text
    return upload["id"]


def test_a_model_bundle_is_uploaded_in_parts_and_registered_as_experimental(env):
    data = bundle(declared_status="candidate")
    assert len(data) > PART_BYTES  # it needs several parts
    upload = send(env.client, data, "model", "refit_mbc_only.zip", STAFF)
    registered = env.client.post("/models/upload", json={"upload_id": upload}, headers=STAFF)
    assert registered.status_code == 201, registered.text
    record = registered.json()
    # Never approved on arrival, whatever the descriptor declares.
    assert record["model_id"] == "uploaded_refit_mbc_only" and record["status"] == "experimental"
    assert record["policy"] == "mbc_only" and record["trees"] == 300
    assert record["upload"]["sha256"] == uploads.sha256(data)
    assert record["artifact_paths"]["model"].startswith("uploaded_refit_mbc_only/bundle/")
    assert env.store.blobs[uploads.store_name("uploaded_refit_mbc_only")] == data
    # The same model ID cannot be uploaded twice.
    again = send(env.client, data, "model", "again.zip", STAFF)
    refused = env.client.post("/models/upload", json={"upload_id": again}, headers=STAFF)
    assert refused.status_code == 422 and "immutable" in refused.json()["detail"]
    # A restarted replica unpacks the bundle again from the store before loading it.
    shutil.rmtree(uploads.upload_root() / "uploaded_refit_mbc_only")
    operational._models.clear()
    model = operational.OperationalModel(record).load()
    assert model.info["policy"] == "mbc_only"
    assert operational.OperationalModel(record).health_check()


def test_visitors_cannot_upload_a_model(env):
    started = env.client.post(
        "/uploads", json={"purpose": "model", "name": "m.zip", "size": 10}, headers=VISITOR
    )
    assert started.status_code == 401 and "staff access key" in started.json()["detail"]
    blocked = env.client.post("/models/upload", json={"upload_id": "0" * 32}, headers=VISITOR)
    assert blocked.status_code == 401


def test_a_bundle_that_fails_a_check_leaves_nothing_behind(env):
    changed = bundle("uploaded_bad", checksums={"manifest": "0" * 64})
    upload = send(env.client, changed, "model", "bad.zip", STAFF)
    refused = env.client.post("/models/upload", json={"upload_id": upload}, headers=STAFF)
    assert refused.status_code == 422, refused.text
    assert "checksum" in refused.json()["detail"]
    assert not (uploads.upload_root() / "uploaded_bad").exists()
    # A file name that climbs out of the bundle is refused before anything is unpacked.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("registration.yaml", "model_id: x\nartifacts: {model: m.cbm}\n")
        archive.writestr("../outside.cbm", b"x")
    upload = send(env.client, buffer.getvalue(), "model", "unsafe.zip", STAFF)
    unsafe = env.client.post("/models/upload", json={"upload_id": upload}, headers=STAFF)
    assert unsafe.status_code == 422 and "unsafe file name" in unsafe.json()["detail"]


def test_an_unknown_model_cannot_be_chosen_for_a_forecast(env):
    response = env.client.post(
        "/operations",
        json={"action": "run_forecast", "model_id": "no_such_model", "actor": "Joe N"},
        headers=VISITOR,
    )
    assert response.status_code == 422 and "no_such_model" in response.json()["detail"]


def test_a_large_copilot_file_arrives_in_parts(env):
    text = ("Floods were reported in Garissa on 25 October. " * 120_000).encode()
    assert len(text) > PART_BYTES
    upload = send(env.client, text, "attachment", "field-report.txt", VISITOR)
    saved = env.client.post("/chat/attachments/staged", json={"upload_id": upload}, headers=VISITOR)
    assert saved.status_code == 201, saved.text
    record = saved.json()
    assert record["name"] == "field-report.txt" and record["kind"] == "text"
    assert record["bytes"] == len(text) and record["truncated"] is True
    # Another visitor cannot finish someone else's upload.
    other = send(env.client, b"hello", "attachment", "note.txt", VISITOR)
    stolen = env.client.post(
        "/chat/attachments/staged",
        json={"upload_id": other},
        headers={"X-Visitor-Id": "f" * 32},
    )
    assert stolen.status_code == 404
