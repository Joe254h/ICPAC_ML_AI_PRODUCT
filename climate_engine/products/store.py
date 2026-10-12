"""Object storage for product packages, for hosts without a persistent file system.

With ``PACKAGE_STORE_CONNECTION`` (an Azure Storage connection string) set, every package
the platform publishes or updates is copied to the ``PACKAGE_STORE_CONTAINER`` blob
container, and a package missing from local disk is fetched from it. ``RUN_ROOT`` is then a
cache: a replica that restarts or scales to zero loses nothing, and packages written on the
HPC can be uploaded to the container and imported. Without the setting, packages live on
disk only (Docker Compose, a mounted volume).

Blob names are ``<forecast_id>/<file>``. The manifest is uploaded last and checked after a
fetch, so a reader never trusts a partial copy. Draft bulletins keep their frozen map as
``bulletins/<id>/map.png`` in the same container.
"""

import json
import os
import shutil
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

CONNECTION_ENV = "PACKAGE_STORE_CONNECTION"
CONTAINER_ENV = "PACKAGE_STORE_CONTAINER"
DEFAULT_CONTAINER = "forecast-packages"
MANIFEST = "manifest.json"


class ContainerClient(Protocol):
    """The part of ``azure.storage.blob.ContainerClient`` the store uses."""

    def upload_blob(self, name: str, data: bytes, *, overwrite: bool | None = ...) -> Any: ...

    def list_blobs(self, name_starts_with: str | None = ..., **kwargs: Any) -> Any: ...

    def download_blob(self, blob: str, **kwargs: Any) -> Any: ...


class PackageStore:
    def __init__(self, container: ContainerClient):
        self.container = container

    def upload(self, directory: Path) -> None:
        """Upload exactly one manifest snapshot and its files, manifest last."""
        from climate_engine.products.package import check_package, file_path

        directory = Path(directory).resolve()
        manifest_bytes = (directory / MANIFEST).read_bytes()
        manifest = json.loads(manifest_bytes)
        problems = check_package(directory)
        if problems:
            raise ValueError(f"Package failed its checks: {problems}")
        for logical in sorted(manifest["files"]):
            path = file_path(directory, logical, manifest)
            name = f"{directory.name}/{path.relative_to(directory).as_posix()}"
            self.container.upload_blob(name, path.read_bytes(), overwrite=True)
        self.container.upload_blob(f"{directory.name}/{MANIFEST}", manifest_bytes, overwrite=True)

    def put(self, name: str, data: bytes) -> None:
        """Store one object, e.g. a draft bulletin's frozen map (``bulletins/<id>/map.png``)."""
        self.container.upload_blob(name, data, overwrite=True)

    def get(self, name: str) -> bytes | None:
        """One stored object, or None when the store does not hold it."""
        if name not in {blob.name for blob in self.container.list_blobs(name_starts_with=name)}:
            return None
        return self.container.download_blob(name).readall()

    def fetch(self, forecast_id: str, root: Path) -> bool:
        """Download a package into ``root/forecast_id``; False when the store lacks it."""
        from climate_engine.products.package import check_package, file_path

        prefix = f"{forecast_id}/"
        names = [blob.name for blob in self.container.list_blobs(name_starts_with=prefix)]
        if f"{prefix}{MANIFEST}" not in names:
            return False
        manifest_bytes = self.container.download_blob(f"{prefix}{MANIFEST}").readall()
        manifest = json.loads(manifest_bytes)
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=True)
        staging = root / f".{forecast_id}.fetch-{uuid.uuid4().hex[:8]}"
        try:
            for logical in manifest["files"]:
                target = file_path(staging, logical, manifest)
                name = prefix + target.relative_to(staging.resolve()).as_posix()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.container.download_blob(name).readall())
            (staging / MANIFEST).write_bytes(manifest_bytes)
            problems = check_package(staging)
            if problems:
                raise ValueError(f"Downloaded package failed its checks: {problems}")
            destination = root / forecast_id
            if destination.exists():  # fetched meanwhile by another request
                shutil.rmtree(staging)
            else:
                staging.rename(destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return True


@lru_cache(maxsize=4)
def _store(connection: str, container_name: str) -> PackageStore:
    from azure.storage.blob import BlobServiceClient

    container = BlobServiceClient.from_connection_string(connection).get_container_client(
        container_name
    )
    if not container.exists():
        container.create_container()
    return PackageStore(container)


def package_store() -> PackageStore | None:
    """The configured package store, or None when packages live on disk only."""
    connection = os.getenv(CONNECTION_ENV)
    if not connection:
        return None
    return _store(connection, os.getenv(CONTAINER_ENV) or DEFAULT_CONTAINER)
