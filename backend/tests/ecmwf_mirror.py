"""A local ECMWF Open Data mirror for tests: real GRIB2 files and .index files laid out as
on data.ecmwf.int, served over HTTP so the official client runs unchanged."""

import argparse
import json
import shutil
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

STEP = 2.5  # coarse global grid keeps the files small; the decoder reads it from the GRIB


def rainfall_m(number: int, step: int) -> np.ndarray:
    """Accumulated tp (m) on the 2.5 degree global grid: grows with the step and member."""
    lat = np.arange(90.0, -90.0 - 1e-9, -STEP)
    lon = np.arange(-180.0, 180.0, STEP)
    pattern = 0.004 + 0.003 * np.cos(np.deg2rad(lat))[:, None] * (1 + np.sin(np.deg2rad(lon)))
    return pattern * (step / 168.0) * (1 + 0.05 * number)


def message(codes, number: int, step: int, day: date, kind: str = "pf", param: int = 228):
    gid = codes.codes_grib_new_from_samples("GRIB2")
    for key, value in [
        ("centre", "ecmf"),
        ("setLocalDefinition", 1),
        ("stream", "enfo"),
        ("type", kind),
        ("productDefinitionTemplateNumber", 11),
        ("paramId", param),
        ("number", number),
        ("numberOfForecastsInEnsemble", 50),
        ("dataDate", int(day.strftime("%Y%m%d"))),
        ("dataTime", 0),
        ("stepType", "accum"),
        ("startStep", 0),
        ("endStep", step),
        ("gridType", "regular_ll"),
        ("Ni", int(360 / STEP)),
        ("Nj", int(180 / STEP) + 1),
        ("latitudeOfFirstGridPointInDegrees", 90.0),
        ("longitudeOfFirstGridPointInDegrees", -180.0),
        ("latitudeOfLastGridPointInDegrees", -90.0),
        ("longitudeOfLastGridPointInDegrees", 180.0 - STEP),
        ("iDirectionIncrementInDegrees", STEP),
        ("jDirectionIncrementInDegrees", STEP),
        ("jScansPositively", 0),
        ("iScansNegatively", 0),
    ]:
        codes.codes_set(gid, key, value)
    codes.codes_set_values(gid, rainfall_m(number, step).ravel())
    data = codes.codes_get_message(gid)
    codes.codes_release(gid)
    return data


def build(root: Path, day: date, members: int = 3, steps=(168, 336)) -> Path:
    """Files for one 00 UTC ENS run: tp for the control and perturbed members, plus another
    parameter, so the client's index filtering is exercised."""
    import eccodes as codes

    folder = root / day.strftime("%Y%m%d") / "00z" / "ifs" / "0p25" / "enfo"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = day.strftime("%Y%m%d") + "000000"
    for step in steps:
        blob, index = b"", []
        entries = [("cf", 0, 228)] + [("pf", n, 228) for n in range(1, members + 1)]
        entries += [("pf", 1, 167)]  # 2 m temperature, which must not be downloaded
        for kind, number, param in entries:
            data = message(codes, number, step, day, kind, param)
            index.append(
                {
                    "domain": "g",
                    "date": day.strftime("%Y%m%d"),
                    "time": "0000",
                    "expver": "0001",
                    "class": "od",
                    "type": kind,
                    "stream": "enfo",
                    "step": str(step),
                    "levtype": "sfc",
                    "number": str(number),
                    "param": "tp" if param == 228 else "2t",
                    "_offset": len(blob),
                    "_length": len(data),
                }
            )
            blob += data
        (folder / f"{stamp}-{step}h-enfo-ef.grib2").write_bytes(blob)
        (folder / f"{stamp}-{step}h-enfo-ef.index").write_text(
            "\n".join(json.dumps(line) for line in index) + "\n"
        )
    return folder


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextmanager
def serve(root: Path):
    """An HTTP server for ``root`` with byte-range support; yields its base URL."""
    handler = partial(_RangeHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


class _RangeHandler(_Quiet):
    """Single byte ranges, as the cloud mirrors serve them."""

    def send_head(self):
        header = self.headers.get("Range")
        path = Path(self.translate_path(self.path))
        if not header or not path.is_file():
            return super().send_head()
        start, end = header.removeprefix("bytes=").split("-")
        data = path.read_bytes()
        first, last = int(start), min(int(end), len(data) - 1)
        chunk = data[first : last + 1]
        self.send_response(206)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Range", f"bytes {first}-{last}/{len(data)}")
        self.send_header("Content-Length", str(len(chunk)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        import io

        return io.BytesIO(chunk)


def main() -> None:
    """Build and serve a mirror holding yesterday's run, the newest a forecaster would find
    (browser tests point ECMWF_OPENDATA_MIRRORS at it)."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8998)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--members", type=int, default=3)
    args = parser.parse_args()
    day = args.date or datetime.now(timezone.utc).date() - timedelta(days=1)
    shutil.rmtree(args.root, ignore_errors=True)
    build(args.root, day, args.members)
    handler = partial(_RangeHandler, directory=str(args.root))
    print(f"ECMWF mirror of the {day} 00 UTC run on http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
