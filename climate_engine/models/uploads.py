"""Model bundles uploaded through the website.

A bundle is a ZIP file holding one registration descriptor (a ``.yaml`` file written like
those in config/model_registry/, its artifact paths relative to the top of the ZIP) and the
files it names, usually the bundle folder the training pipeline exports. The ZIP may also
hold everything inside one top folder. It is unpacked under MODEL_UPLOAD_ROOT/<model_id>
(RUN_ROOT/model_uploads by default) and then checked and registered exactly like a reviewed
descriptor: every checksum, the bundle manifest, the 24-input schema, the domain mask and a
smoke prediction. Nothing in the bundle is run as code; models load from CatBoost's own
format and NumPy arrays without pickles.

With a package store (Blob Storage), the ZIP itself is kept there as models/<model_id>.zip,
so a replica that restarts unpacks it again before the model is loaded.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from climate_engine.core import ROOT

MAX_BYTES = 300 * 1024**2
MAX_UNPACKED = 1024**3
MAX_FILES = 500
DESCRIPTOR = "registration.yaml"
#: Set on an uploaded descriptor: its artifact paths are relative to upload_root().
STORE_FLAG = "artifact_store"


class BundleError(ValueError):
    """The bundle cannot be accepted; the message says why, in words."""


def upload_root() -> Path:
    default = Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs"))) / "model_uploads"
    return Path(os.getenv("MODEL_UPLOAD_ROOT") or default).resolve()


def store_name(model_id: str) -> str:
    return f"models/{model_id}.zip"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive(data: bytes) -> zipfile.ZipFile:
    if len(data) > MAX_BYTES:
        raise BundleError(f"A model bundle can be up to {MAX_BYTES // 1024**2} MB")
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BundleError("The file is not a ZIP archive") from exc


def _files(archive: zipfile.ZipFile) -> tuple[str, list[zipfile.ZipInfo]]:
    """The archive's files and the folder they share, refusing unsafe or oversized ones."""
    infos = [i for i in archive.infolist() if not i.is_dir()]
    if not infos:
        raise BundleError("The ZIP archive is empty")
    if len(infos) > MAX_FILES:
        raise BundleError(f"A model bundle can hold up to {MAX_FILES} files")
    total = 0
    for info in infos:
        path = PurePosixPath(info.filename)
        if (
            info.filename.startswith("/")
            or "\\" in info.filename
            or ".." in path.parts
            or ":" in path.parts[0]
            or stat.S_ISLNK(info.external_attr >> 16)
        ):
            raise BundleError(f"The bundle has an unsafe file name: {info.filename}")
        total += info.file_size
    if total > MAX_UNPACKED:
        raise BundleError(f"Unpacked, a model bundle can be up to {MAX_UNPACKED // 1024**3} GB")
    # Everything inside one folder (a compressed folder) counts from that folder.
    tops = {PurePosixPath(i.filename).parts[0] for i in infos}
    base = ""
    if len(tops) == 1 and all(len(PurePosixPath(i.filename).parts) > 1 for i in infos):
        top = next(iter(tops))
        if not any(_is_yaml(i.filename) and i.filename.count("/") == 0 for i in infos):
            base = top + "/"
    return base, infos


def _is_yaml(name: str) -> bool:
    return name.lower().endswith((".yaml", ".yml"))


def read_descriptor(data: bytes) -> dict[str, Any]:
    """The bundle's registration descriptor: the one ``.yaml`` file at its top."""
    with _archive(data) as archive:
        base, infos = _files(archive)
        found = [
            i
            for i in infos
            if i.filename.startswith(base)
            and "/" not in i.filename[len(base) :]
            and _is_yaml(i.filename)
        ]
        if len(found) != 1:
            raise BundleError(
                "Put exactly one registration descriptor (.yaml) at the top of the ZIP, "
                "next to the bundle folder"
            )
        try:
            descriptor = yaml.safe_load(archive.read(found[0]).decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise BundleError("The registration descriptor is not readable YAML") from exc
    if not isinstance(descriptor, dict) or not isinstance(descriptor.get("artifacts"), dict):
        raise BundleError("The registration descriptor must list the bundle's artifacts")
    return descriptor


def unpack(data: bytes, model_id: str) -> Path:
    """Unpack a bundle under upload_root()/<model_id> and write its descriptor there, with
    the artifact paths made relative to upload_root(). Returns the descriptor's path."""
    descriptor = read_descriptor(data)
    target = upload_root() / model_id
    for kind, artifact in descriptor["artifacts"].items():
        parts = PurePosixPath(str(artifact)).parts
        if not parts or str(artifact).startswith("/") or ".." in parts or "\\" in str(artifact):
            raise BundleError(f"The {kind} artifact must be a path inside the bundle")
    _extract(data, target)
    # A reviewer approves an uploaded model on the Models page; it never arrives approved.
    descriptor["declared_status"] = "experimental"
    descriptor[STORE_FLAG] = "upload"
    descriptor["artifacts"] = {
        kind: f"{model_id}/{path}" for kind, path in descriptor["artifacts"].items()
    }
    path = target / DESCRIPTOR
    path.write_text(yaml.safe_dump(descriptor, sort_keys=False), encoding="utf-8")
    return path


def _extract(data: bytes, target: Path) -> None:
    with _archive(data) as archive:
        base, infos = _files(archive)
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for info in infos:
            name = info.filename[len(base) :]
            if not info.filename.startswith(base) or ("/" not in name and _is_yaml(name)):
                continue  # outside the bundle, or the descriptor (written separately)
            destination = (target / name).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise BundleError(f"The bundle has an unsafe file name: {info.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            # A ZIP member never yields more than its declared size.
            with archive.open(info) as source, destination.open("wb") as out:
                shutil.copyfileobj(source, out)


def ensure_local(record: dict[str, Any]) -> None:
    """Unpack an uploaded model's bundle again when this replica does not hold it (a
    restart), from the copy kept in the package store."""
    upload = record.get("upload")
    if not upload:
        return
    target = upload_root() / record["model_id"]
    if target.is_dir():
        return
    from climate_engine.products.store import package_store

    store = package_store()
    data = store.get(store_name(record["model_id"])) if store else None
    if data is None:
        raise FileNotFoundError(
            f"The uploaded bundle of {record['model_id']} is not on this server or in the store"
        )
    if sha256(data) != upload["sha256"]:
        raise ValueError(f"The stored bundle of {record['model_id']} changed after registration")
    _extract(data, target)
