"""Object storage for product packages, for hosts without a persistent file system.

With ``PACKAGE_STORE_CONNECTION`` (an Azure Storage connection string) set, every package
the platform publishes or updates is copied to the ``PACKAGE_STORE_CONTAINER`` blob
container, and a package missing from local disk is fetched from it. ``RUN_ROOT`` is then a
cache: a replica that restarts or scales to zero loses nothing, and packages written on the
HPC can be uploaded to the container and imported. Without the setting, packages live on
disk only (Docker Compose, a mounted volume).

Blob names are ``<forecast_id>/<file>``. The manifest is uploaded last and checked after a
fetch, so a reader never trusts a partial copy.
"""

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
        """Copy a package (every non-hidden file) to the container, manifest last."""
        directory = Path(directory)
        files = sorted(
            path
            for path in directory.rglob("*")
            if path.is_file()
            and not any(part.startswith(".") for part in path.relative_to(directory).parts)
        )
        files.sort(key=lambda path: path.name == MANIFEST)
        for path in files:
            name = f"{directory.name}/{path.relative_to(directory).as_posix()}"
            self.container.upload_blob(name, path.read_bytes(), overwrite=True)

    def fetch(self, forecast_id: str, root: Path) -> bool:
        """Download a package into ``root/forecast_id``; False when the store lacks it."""
        prefix = f"{forecast_id}/"
        names = [blob.name for blob in self.container.list_blobs(name_starts_with=prefix)]
        if f"{prefix}{MANIFEST}" not in names:
            return False
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        staging = root / f".{forecast_id}.fetch-{uuid.uuid4().hex[:8]}"
        try:
            for name in names:
                target = staging / name[len(prefix) :]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.container.download_blob(name).readall())
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
