"""Integrity of the HPC artifact package committed under artifacts/.

The package's own SHA256SUMS.txt (artifacts/hpc_package/) lists paths relative to the
package root: ./artifacts/..., ./cartography/..., ./fixtures/... map onto the repository
root, and package-root files (README_PACKAGE.txt, UPLOAD_MAP.txt) live beside the list.
"""

from dataclasses import dataclass
from pathlib import Path

from climate_engine.core import ROOT
from climate_engine.provenance import file_checksum

PACKAGE = ROOT / "artifacts" / "hpc_package"
SUMS = PACKAGE / "SHA256SUMS.txt"
REPO_PREFIXES = ("artifacts/", "cartography/", "fixtures/")
GITHUB_WARN_BYTES = 50 * 1024 * 1024
GITHUB_LIMIT_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class ArtifactCheck:
    package_path: str
    path: Path
    expected: str
    actual: str | None
    size: int | None

    @property
    def ok(self) -> bool:
        return self.actual == self.expected

    @property
    def status(self) -> str:
        if self.actual is None:
            return "missing"
        return "ok" if self.ok else "checksum mismatch"


def expected_checksums(sums: Path = SUMS) -> dict[str, str]:
    """Package path -> SHA256 from the HPC-generated checksum list."""
    out: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        if len(digest) != 64 or not name:
            raise ValueError(f"Malformed checksum line: {line!r}")
        out[name.strip().removeprefix("./")] = digest
    return out


def resolve(package_path: str, root: Path = ROOT) -> Path:
    if package_path.startswith(REPO_PREFIXES):
        return root / package_path
    return root / "artifacts" / "hpc_package" / package_path


def verify_package(root: Path = ROOT, sums: Path | None = None) -> list[ArtifactCheck]:
    checks = []
    for name, digest in expected_checksums(sums or root / SUMS.relative_to(ROOT)).items():
        path = resolve(name, root)
        exists = path.is_file()
        checks.append(
            ArtifactCheck(
                name,
                path,
                digest,
                file_checksum(path) if exists else None,
                path.stat().st_size if exists else None,
            )
        )
    return checks


def expected_checksum(repo_path: str, root: Path = ROOT) -> str:
    """Checksum the HPC recorded for a repository path such as artifacts/mbc/x.npz."""
    sums = expected_checksums(root / SUMS.relative_to(ROOT))
    if repo_path not in sums:
        raise KeyError(f"{repo_path} is not listed in the HPC checksum file")
    return sums[repo_path]
