"""Run code/icpac_resume_missing.py's downloads in parallel: several ECDS requests at once.

    python code/parallel_resume.py --manifest M.jsonl                 # dry run: counts
    python code/parallel_resume.py --manifest M.jsonl --execute --workers 4
    nohup python code/parallel_resume.py --manifest M.jsonl --execute --workers 4 \
        > logs/ecds_parallel.log 2>&1 &

It imports icpac_resume_missing.py (same folder) and uses its read_manifest, validate_grib
and download, so files are validated, written through temporary files and never
overwritten exactly as before. Each worker has its own ECDS client. A request that fails
(queue full, rate limit, network) is retried with a growing wait; after --retries it is
logged FAILED and the next run picks it up again, because only valid files count as done.
ECDS queues requests per user: 3-4 workers is usually the useful maximum.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import icpac_resume_missing as base  # noqa: E402

_local = threading.local()
_lock = threading.Lock()


def client():
    """One ECDS client per worker thread."""
    if not hasattr(_local, "client"):
        import cdsapi

        key = os.environ.get("ECDS_API_KEY")
        if not key:
            raise RuntimeError("ECDS_API_KEY is missing")
        _local.client = cdsapi.Client(url="https://ecds.ecmwf.int/api", key=key, quiet=True)
    return _local.client


def fetch(record, retries: int, wait: float):
    for attempt in range(1, retries + 1):
        status, detail = base.download(client(), record)
        if status in ("DOWNLOADED", "TARGET_APPEARED"):
            return status, detail
        if status == "DOWNLOAD_INVALID" or attempt == retries:
            return status, f"attempt {attempt}: {detail}"
        time.sleep(wait * attempt)  # queue full or rate limited: back off, then retry
    return "FAILED", "no attempt made"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--manifest", type=Path, default=base.DEFAULT_MANIFEST)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="submit at most N requests (0: all)")
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--wait", type=float, default=120, help="seconds before a retry (x attempt)")
    ap.add_argument("--stagger", type=float, default=5, help="seconds between first submissions")
    args = ap.parse_args()

    records = base.read_manifest(args.manifest)
    todo, counts = [], Counter()
    for r in records:
        if r["_resolved_target"].exists():
            valid, _ = base.validate_grib(r["_resolved_target"])
            counts["EXISTS_VALIDATED" if valid else "EXISTS_INVALID"] += 1
        else:
            todo.append(r)
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(records)} requests: {counts['EXISTS_VALIDATED']} done, "
          f"{counts['EXISTS_INVALID']} invalid (left alone), {len(todo)} to download "
          f"with {args.workers} workers", flush=True)
    if not args.execute:
        print("Dry run: nothing submitted. Add --execute.")
        return 0

    base.LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logfile = base.LOG_DIR / f"parallel_{stamp}_{os.getpid()}.jsonl"
    started = time.time()
    done = 0
    with logfile.open("w") as log, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {}
        for i, r in enumerate(todo):
            futures[pool.submit(fetch, r, args.retries, args.wait)] = r
            if i < args.workers:
                time.sleep(args.stagger)  # do not hit the queue with every worker at once
        for fut in as_completed(futures):
            r = futures[fut]
            try:
                status, detail = fut.result()
            except Exception as exc:
                status, detail = "FAILED", f"{type(exc).__name__}: {exc}"
            with _lock:
                counts[status] += 1
                done += 1
                base.log_result(log, r, status, detail)
                rate = done / max(time.time() - started, 1) * 3600
                left = (len(todo) - done) / rate if rate else 0
                print(f"  {done}/{len(todo)} finished, {rate:.1f}/hour, about {left:.1f} h left",
                      flush=True)

    print("\n========== PARALLEL DOWNLOAD SUMMARY ==========")
    for status, n in sorted(counts.items()):
        print(f"{status}: {n}")
    print(f"Log: {logfile}\nRerun the same command to retry anything FAILED.")
    print(json.dumps(dict(counts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
