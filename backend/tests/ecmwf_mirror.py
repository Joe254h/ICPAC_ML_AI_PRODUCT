"""A local mirror for tests: ECMWF Open Data (real GRIB2 files and .index files laid out as
on data.ecmwf.int, so the official client runs unchanged) and, under /chc, a CHIRPS
preliminary dekad laid out as on data.chc.ucsb.edu (with its directory listing). The
rainfall in both is a made-up pattern: it exercises the chain, it is not weather."""

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


#: Upper-air fields of the mirror: GRIB paramId and a plausible value, with more levels than
#: the AI/ML model reads, so the client's level filtering is exercised.
PRESSURE = {
    "q": (133, 0.008),
    "u": (131, 5.0),
    "v": (132, -3.0),
    "t": (130, 280.0),
    "gh": (156, 5800.0),
}
PRESSURE_LEVELS = (925, 850, 700, 500, 200)


def pressure_message(codes, name: str, level: int, number: int, step: int, day: date) -> bytes:
    param, base = PRESSURE[name]
    lat = np.arange(90.0, -90.0 - 1e-9, -STEP)
    lon = np.arange(-180.0, 180.0, STEP)
    # Level, member and hour change the field a little; the pattern stays plausible.
    variation = 0.02 * np.cos(np.deg2rad(lat))[:, None] * np.sin(np.deg2rad(lon + step))
    scale = 1 + variation + 0.01 * number - 0.0001 * (level - 850)
    gid = codes.codes_grib_new_from_samples("GRIB2")
    for key, value in [
        ("centre", "ecmf"),
        ("setLocalDefinition", 1),
        ("stream", "enfo"),
        ("type", "pf"),
        ("productDefinitionTemplateNumber", 1),
        ("paramId", param),
        ("typeOfLevel", "isobaricInhPa"),
        ("level", level),
        ("number", number),
        ("numberOfForecastsInEnsemble", 50),
        ("dataDate", int(day.strftime("%Y%m%d"))),
        ("dataTime", 0),
        ("stepType", "instant"),
        ("step", step),
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
    codes.codes_set_values(gid, (base * scale).ravel())
    data = codes.codes_get_message(gid)
    codes.codes_release(gid)
    return data


def build(root: Path, day: date, members: int = 3, steps=(168, 336), pressure_steps=()) -> Path:
    """Files for one 00 UTC ENS run: tp for the control and perturbed members, plus another
    parameter, so the client's index filtering is exercised; with ``pressure_steps``, also
    the upper-air fields of the perturbed members at those forecast hours."""
    import eccodes as codes

    folder = root / day.strftime("%Y%m%d") / "00z" / "ifs" / "0p25" / "enfo"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = day.strftime("%Y%m%d") + "000000"
    for step in sorted(set(steps) | set(pressure_steps)):
        blob, index = b"", []

        def add(data: bytes, line: dict) -> None:
            nonlocal blob
            base = {
                "domain": "g",
                "date": day.strftime("%Y%m%d"),
                "time": "0000",
                "expver": "0001",
                "class": "od",
                "stream": "enfo",
                "step": str(step),
            }
            index.append({**base, **line, "_offset": len(blob), "_length": len(data)})
            blob += data

        if step in steps:
            entries = [("cf", 0, 228)] + [("pf", n, 228) for n in range(1, members + 1)]
            entries += [("pf", 1, 167)]  # 2 m temperature, which must not be downloaded
            for kind, number, param in entries:
                add(
                    message(codes, number, step, day, kind, param),
                    {
                        "type": kind,
                        "levtype": "sfc",
                        "number": str(number),
                        "param": "tp" if param == 228 else "2t",
                    },
                )
        if step in pressure_steps:
            for name in PRESSURE:
                for level in PRESSURE_LEVELS:
                    for number in range(1, members + 1):
                        add(
                            pressure_message(codes, name, level, number, step, day),
                            {
                                "type": "pf",
                                "levtype": "pl",
                                "levelist": str(level),
                                "number": str(number),
                                "param": name,
                            },
                        )
        (folder / f"{stamp}-{step}h-enfo-ef.grib2").write_bytes(blob)
        (folder / f"{stamp}-{step}h-enfo-ef.index").write_text(
            "\n".join(json.dumps(line) for line in index) + "\n"
        )
    return folder


def build_chirps_dekad(root: Path, today: date) -> Path:
    """The newest dekad that has ended before ``today``, as a CHIRPS preliminary dekadal
    NetCDF over the region (the real files are global)."""
    import xarray as xr

    from climate_engine.inputs.chirps_dekad import Dekad

    year, month = today.year, today.month
    if today.day > 20:
        dekad = Dekad(year, month, 2)
    elif today.day > 10:
        dekad = Dekad(year, month, 1)
    else:
        previous = date(year, month, 1) - timedelta(days=1)
        dekad = Dekad(previous.year, previous.month, 3)
    lat = np.round(np.arange(-14.975, 24.976, 0.05), 3)
    lon = np.round(np.arange(19.025, 53.976, 0.05), 3)
    pattern = 40 * (1 + np.sin(np.deg2rad(lat * 9))[:, None] * np.cos(np.deg2rad(lon * 7)))
    folder = root / "chc/products/CHIRPS-2.0/prelim/global_dekad/netcdf"
    folder.mkdir(parents=True, exist_ok=True)
    data = xr.Dataset(
        {"precip": (("time", "latitude", "longitude"), pattern[None].astype(np.float32))},
        coords={
            "time": [np.datetime64(dekad.start.isoformat())],
            "latitude": lat,
            "longitude": lon,
        },
    )
    path = folder / dekad.name
    data.to_netcdf(path)
    return path


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
    """Build and serve a mirror holding yesterday's run, the newest a forecaster would find,
    and the newest ended CHIRPS dekad (browser tests point ECMWF_OPENDATA_MIRRORS at the
    mirror and CHIRPS_BASE_URL at its /chc folder)."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8998)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--members", type=int, default=3)
    args = parser.parse_args()
    day = args.date or datetime.now(timezone.utc).date() - timedelta(days=1)
    shutil.rmtree(args.root, ignore_errors=True)
    build(args.root, day, args.members)
    build_chirps_dekad(args.root, day + timedelta(days=1))
    handler = partial(_RangeHandler, directory=str(args.root))
    print(f"ECMWF mirror of the {day} 00 UTC run on http://127.0.0.1:{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
