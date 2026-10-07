"""Verify the committed HPC artifacts against the HPC-generated SHA256SUMS.txt.

python -m scripts.verify_artifacts      # exit status 1 on any missing or changed file
"""

import sys

from climate_engine.artifacts import GITHUB_LIMIT_BYTES, GITHUB_WARN_BYTES, verify_package

if __name__ == "__main__":
    failures = 0
    for check in verify_package():
        size = f"{check.size / 1e6:9.3f} MB" if check.size is not None else "        -   "
        note = ""
        if check.size and check.size > GITHUB_LIMIT_BYTES:
            note = "  exceeds GitHub's 100 MB limit: use Git LFS"
        elif check.size and check.size > GITHUB_WARN_BYTES:
            note = "  above GitHub's 50 MB warning size"
        print(f"{check.status:18s} {size}  {check.package_path}{note}")
        failures += not check.ok
    print(f"{'FAILED' if failures else 'OK'}: {failures} problem(s)")
    sys.exit(1 if failures else 0)
