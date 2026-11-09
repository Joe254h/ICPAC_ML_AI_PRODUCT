"""CHIRPS v2.0 observed rainfall from the Climate Hazards Center (CHC) server.

Files are read the way ICPAC's climate monitoring framework reads them: they are found by
listing their directory on the server (never by guessing a name), only files not yet held
are downloaded, transient failures are retried with a doubling wait, every file is checked
before use, and what is kept is cropped to the region (a box containing the framework's
Greater Horn of Africa domain, 20-53 E, 15 S - 24 N).

Week-2 verification uses the daily files: a forecast initialised on day D 00 UTC is valid
from D+7 00 UTC to D+14 00 UTC, so its observation is the sum of the seven daily totals
D+7 ... D+13. Each day is read from the final product when it has been published, else
from the preliminary product; the product used for every day is recorded.

CHIRPS is a 0.05 degree grid whose cells line up with the model grid, so cells are taken
by coordinate (checked to within 1e-4 degree), never resampled. The GeoTIFF's own
georeferencing tags are read; nothing about its extent is assumed. Cells without data
(CHIRPS marks them -9999) stay missing and are left out of the verification.
"""

import gzip
import hashlib
import io
import os
import re
import socket
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpcore
import httpx
import numpy as np
import xarray as xr

from climate_engine.core import config
from climate_engine.operational.grid import DomainGrid

DAYS = 7
PIXEL_IS_POINT = 2


class CHIRPSUnavailable(LookupError):
    """A day of the window is not published yet in either product."""


@dataclass
class Day:
    day: date
    product: str  # "final" or "prelim"
    url: str
    sha256: str
    missing_domain_cells: int


@dataclass
class WeekTotal:
    start: date  # first day (00 UTC of the valid window)
    values: np.ndarray  # (latitude, longitude) on the model grid, mm; NaN outside/no data
    days: list[Day] = field(default_factory=list)

    @property
    def end(self) -> date:
        return self.start + timedelta(days=DAYS)

    @property
    def products(self) -> list[str]:
        return sorted({d.product for d in self.days})

    def record(self) -> dict[str, Any]:
        return {
            "valid_start": self.start.isoformat(),
            "valid_end": self.end.isoformat(),
            "products": self.products,
            "days": [
                {
                    "day": d.day.isoformat(),
                    "product": d.product,
                    "url": d.url,
                    "sha256": d.sha256,
                    "missing_domain_cells": d.missing_domain_cells,
                }
                for d in self.days
            ],
        }


CHC = "https://data.chc.ucsb.edu"


def settings() -> dict[str, Any]:
    """The CHIRPS settings; CHIRPS_BASE_URL serves the same paths from another server
    (a local copy or test mirror laid out like data.chc.ucsb.edu)."""
    cfg = dict(config("data_sources")["chirps"])
    base = os.getenv("CHIRPS_BASE_URL")
    if base:
        for key in ("final_dir", "prelim_dir", "dekad_dir"):
            cfg[key] = cfg[key].replace(CHC, base.rstrip("/"))
    return cfg


PRODUCTS = ("final", "prelim")
#: The first bytes of a GeoTIFF (little or big endian); compressed files start with gzip's.
TIFF_MAGIC = (b"II*\x00", b"MM\x00*")
GZIP_MAGIC = b"\x1f\x8b"
DAILY_FILE = re.compile(r"chirps-v2\.0\.\d{4}\.\d{2}\.\d{2}\.tif(?:\.gz)?")


def day_names(day: date) -> tuple[str, str]:
    """The two names a daily file is published under (compressed or not)."""
    stem = f"chirps-v2.0.{day.year}.{day.month:02d}.{day.day:02d}.tif"
    return stem + ".gz", stem


def directory(product: str, year: int) -> str:
    return settings()[f"{product}_dir"].format(year=year)


def window_days(valid_start: date) -> list[date]:
    return [valid_start + timedelta(days=offset) for offset in range(DAYS)]


def window_complete(valid_start: date, today: date | None = None, latency_days: int = 2) -> bool:
    """Whether the last day of the window is old enough for CHIRPS to have published it."""
    today = today or datetime.now(timezone.utc).date()
    return window_days(valid_start)[-1] + timedelta(days=latency_days) <= today


def read_geotiff(data: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray, float | None]:
    """Values, latitude and longitude of the pixel centres, and the nodata value."""
    import tifffile

    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    with tifffile.TiffFile(io.BytesIO(data)) as tif:
        page = tif.pages.first
        values = page.asarray().astype(np.float64)
        tags = {tag.name: tag.value for tag in page.tags.values()}
        geo = tif.geotiff_metadata or {}
    scale = tags.get("ModelPixelScaleTag")
    tie = tags.get("ModelTiepointTag")
    if scale is None or tie is None:
        raise ValueError("The CHIRPS file has no georeferencing")
    sx, sy = float(scale[0]), float(scale[1])
    i, j, x, y = float(tie[0]), float(tie[1]), float(tie[3]), float(tie[4])
    offset = 0.0 if int(geo.get("GTRasterTypeGeoKey", 1)) == PIXEL_IS_POINT else 0.5
    rows, cols = values.shape
    longitude = x + (np.arange(cols) - i + offset) * sx
    latitude = y - (np.arange(rows) - j + offset) * sy
    nodata = tags.get("GDAL_NODATA")
    return values, latitude, longitude, (float(str(nodata).strip("\x00")) if nodata else None)


def _indices(source: np.ndarray, needed: np.ndarray, axis: str) -> np.ndarray:
    order = np.argsort(source)
    position = np.searchsorted(source[order], needed)
    position = np.clip(position, 1, source.size - 1)
    left, right = order[position - 1], order[position]
    pick = np.where(np.abs(source[left] - needed) <= np.abs(source[right] - needed), left, right)
    error = np.abs(source[pick] - needed).max()
    if error > 1e-4:
        raise ValueError(f"CHIRPS {axis} does not line up with the model grid ({error:.4f} deg)")
    return pick


def on_model_grid(
    values: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    grid: DomainGrid,
    nodata: float | None,
) -> np.ndarray:
    """The CHIRPS cells of the model grid (latitude ascending), NaN where there is no data."""
    rows = _indices(latitude, grid.latitude, "latitude")
    cols = _indices(longitude, grid.longitude, "longitude")
    window = values[np.ix_(rows, cols)].astype(np.float64)
    missing = ~np.isfinite(window) | (window < 0)
    if nodata is not None:
        missing |= np.isclose(window, nodata)
    window[missing] = np.nan
    return window


Downloader = Callable[[str], bytes | None]

#: A server that does not accept a connection within this many seconds is down for now;
#: a slow transfer still has the full read timeout.
CONNECT_SECONDS = 15
#: After a server could not be reached, its other files fail at once for this long, so one
#: unreachable server costs one set of retries per pass, not one per file.
UNREACHABLE_SECONDS = 30 * 60
#: A server that refused the service (401, 403, or 429: too many requests) is left alone for
#: this long: asking again at once, file after file, is what gets a client blocked.
REFUSED_SECONDS = 6 * 3600
REFUSALS = (401, 403, 429)
_unreachable: dict[str, tuple[float, str]] = {}


def reset_unreachable() -> None:
    _unreachable.clear()


class _IPv4(httpcore.SyncBackend):
    """Connect over IPv4 only. A container without IPv6 otherwise reports the IPv6
    attempt's "[Errno 97] Address family not supported" in place of the real failure."""

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            addresses = {
                str(info[4][0])
                for info in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise httpcore.ConnectError(f"{host} could not be resolved: {exc}") from exc
        last: Exception | None = None
        for address in sorted(addresses):
            try:
                return super().connect_tcp(address, port, timeout, local_address, socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        assert last is not None
        raise last


def user_agent() -> str:
    """Who is asking: the service and its website, so a data provider can see the requests
    come from one forecast service (and reach its operators) rather than an anonymous
    script."""
    site = os.getenv("PUBLIC_SITE_URL") or "https://www.icpac.net"
    return f"ICPAC-Week2-Forecast-Verification/1.0 (+{site.rstrip('/')})"


def client() -> httpx.Client:
    """An HTTP client for the observation servers: IPv4, a short connect timeout and a long
    read timeout, naming the service. A configured proxy (HTTPS_PROXY) is still used."""
    transport = httpx.HTTPTransport()
    transport._pool = httpcore.ConnectionPool(
        ssl_context=httpx.create_ssl_context(), network_backend=_IPv4()
    )
    return httpx.Client(
        timeout=httpx.Timeout(120, connect=CONNECT_SECONDS),
        follow_redirects=True,
        transport=transport,
        headers={"User-Agent": user_agent()},
    )


def download(url: str) -> bytes | None:
    """The file at ``url``, or None when it is not published (HTTP 404)."""
    with client() as session:
        response = session.get(url)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def _transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, OSError))


def _refused(exc: Exception) -> bool:
    """The server answered that it will not serve this client (now)."""
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in REFUSALS


def _unreached(exc: Exception) -> bool:
    """The server never answered (no connection), as opposed to answering with an error."""
    return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))


def _reason(exc: Exception) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return f"it did not accept a connection within {CONNECT_SECONDS} seconds"
    if isinstance(exc, httpx.ConnectError):
        return f"the connection failed ({exc})"
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        answer = f"{response.status_code} {response.reason_phrase}".strip()
        if response.status_code == 429:
            return f"it asked for fewer requests ({answer})"
        if response.status_code in REFUSALS:
            return f"it refused the requests ({answer})"
        return f"it answered {answer}"
    return str(exc)


class Server:
    """The CHC server: directory listings, and downloads retried with a doubling wait
    (``retries`` attempts, first wait ``retry_wait_seconds``), as in the monitoring
    framework. ``get`` replaces the HTTP download (tests, local copies)."""

    def __init__(
        self,
        get: Downloader | None = None,
        sleep: Callable[[float], None] = time.sleep,
        name: str = "CHIRPS",
    ):
        self.get = get
        self.sleep = sleep
        self.name = name
        self.listings: dict[str, set[str]] = {}
        #: What each directory page held: "listed", "missing" (no page) or "empty" (a page
        #: naming no file), with the page's title.
        self.folders: dict[str, tuple[str, str]] = {}
        #: Years whose files were not at their usual address either: not asked again in
        #: this pass.
        self.unaddressed: set[int] = set()

    def fetch(self, url: str) -> bytes | None:
        cfg = settings()
        attempts, wait = int(cfg["retries"]), float(cfg["retry_wait_seconds"])
        host = urlsplit(url).netloc
        held = _unreachable.get(host)
        if held and held[0] > time.monotonic():
            if held[1].startswith("it refused") or held[1].startswith("it asked"):
                raise CHIRPSUnavailable(
                    f"The {self.name} server {held[1].removeprefix('it ')}; it is left alone "
                    "for a few hours before it is asked again"
                )
            raise CHIRPSUnavailable(
                f"The {self.name} server could not be reached a few minutes ago ({held[1]}); "
                "it is tried again in the next pass"
            )
        for attempt in range(1, attempts + 1):
            try:
                return (self.get or download)(url)
            except Exception as exc:
                if not _transient(exc) or attempt == attempts:
                    if _refused(exc):
                        _unreachable[host] = (time.monotonic() + REFUSED_SECONDS, _reason(exc))
                    elif _unreached(exc):
                        _unreachable[host] = (time.monotonic() + UNREACHABLE_SECONDS, _reason(exc))
                    raise CHIRPSUnavailable(
                        f"The {self.name} server could not be reached after {attempt} "
                        f"attempt{'s' if attempt > 1 else ''}: {_reason(exc)}"
                    ) from exc
                self.sleep(wait)
                wait *= 2
        return None  # pragma: no cover - the loop returns or raises

    def listing(self, url: str, pattern: re.Pattern[str]) -> set[str]:
        """File names matching ``pattern`` in a directory listing (empty if the directory
        does not exist yet, e.g. the next year's)."""
        key = url + "|" + pattern.pattern
        if key not in self.listings:
            page = self.fetch(url)
            text = page.decode("utf-8", "replace") if page else ""
            self.listings[key] = set(pattern.findall(text))
            title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
            state = "listed" if self.listings[key] else ("missing" if page is None else "empty")
            self.folders[url] = (state, " ".join(title[1].split())[:80] if title else "")
        return self.listings[key]

    def unlisted(self, day: date) -> str:
        """Why a day held by no product's listing could not be read, in words."""
        held = [self.folders.get(directory(product, day.year)) for product in PRODUCTS]
        if any(state and state[0] == "listed" for state in held):
            return f"CHIRPS for {day.isoformat()} is not published yet"
        pages = [title for state in held if state for title in [state[1]] if title]
        said = f" (the page says: {pages[0]})" if pages else ""
        found = (
            "could not be found"
            if all(state and state[0] == "missing" for state in held)
            else "name no daily files" + said
        )
        return (
            f"CHIRPS for {day.isoformat()} was not found: the CHIRPS server's {day.year} "
            f"folders of daily files {found}, and the file is not at its usual address either"
        )

    def daily_url(self, product: str, day: date) -> str | None:
        """The URL of a day's file in a product, if the server lists it."""
        folder = directory(product, day.year)
        listed = self.listing(folder, DAILY_FILE)
        for name in day_names(day):
            if name in listed:
                return folder + name
        return None


def crop(
    values: np.ndarray, latitude: np.ndarray, longitude: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The region kept on disk (cell centres inside the configured box), latitude
    ascending."""
    box = settings()["crop"]
    rows = np.flatnonzero((latitude > box["south"]) & (latitude < box["north"]))
    cols = np.flatnonzero((longitude > box["west"]) & (longitude < box["east"]))
    if not rows.size or not cols.size:
        raise ValueError("The CHIRPS file does not cover the region")
    rows = rows[np.argsort(latitude[rows])]
    cols = cols[np.argsort(longitude[cols])]
    return values[np.ix_(rows, cols)], latitude[rows], longitude[cols]


def mirror_url(day: date) -> str | None:
    """The day's final CHIRPS v2.0 from an open mirror (NOAA CoastWatch ERDDAP, which copies
    CHC's daily 0.05 degree files), cut to the region by the mirror; None when switched off
    (``CHIRPS_MIRROR_URL=off``)."""
    base = os.getenv("CHIRPS_MIRROR_URL") or settings().get("mirror")
    if not base or base == "off":
        return None
    box = settings()["crop"]
    moment = f"({day.isoformat()}T00:00:00Z)"
    return (
        f"{base.rstrip('/')}.nc?precip[{moment}:1:{moment}]"
        f"[({box['south']}):1:({box['north']})][({box['west']}):1:({box['east']})]"
    )


def read_mirror(data: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The day's rainfall (mm), latitude and longitude from the mirror's NetCDF."""
    with tempfile.NamedTemporaryFile(suffix=".nc") as handle:
        handle.write(data)
        handle.flush()
        with xr.open_dataset(handle.name) as opened:
            loaded = opened.load()
    precip = loaded["precip"]
    if "time" in precip.dims:
        precip = precip.isel(time=0)
    return (
        np.asarray(precip.values, dtype=np.float64),
        np.asarray(loaded["latitude"].values, dtype=np.float64),
        np.asarray(loaded["longitude"].values, dtype=np.float64),
    )


def _store_file(store: Path, day: date) -> Path:
    return store / "daily" / f"chirps-v2.0.{day.isoformat()}.nc"


def _save_day(store: Path, info: "Day", values, latitude, longitude, nodata) -> None:
    values = values.astype(np.float32)
    missing = ~np.isfinite(values) | (values < 0)
    if nodata is not None:
        missing |= np.isclose(values, nodata)
    values[missing] = np.nan
    path = _store_file(store, info.day)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    xr.Dataset(
        {"precip": (("latitude", "longitude"), values, {"units": "mm/day"})},
        coords={"latitude": latitude, "longitude": longitude},
        attrs={
            "day": info.day.isoformat(),
            "product": info.product,
            "url": info.url,
            "sha256": info.sha256,
        },
    ).to_netcdf(partial)
    partial.replace(path)


def _held_day(store: Path | None, day: date) -> tuple[xr.Dataset, dict] | None:
    if store is None or not _store_file(store, day).exists():
        return None
    with xr.open_dataset(_store_file(store, day)) as data:
        data = data.load()
    return data, dict(data.attrs)


def fetch_day(
    day: date,
    grid: DomainGrid,
    server: Server | None = None,
    store: Path | None = None,
) -> tuple[np.ndarray, Day]:
    """One day on the model grid: the final product if published, else the preliminary
    one. A day already held is reused unless a better product (final) has appeared."""
    server = server or Server()
    held = _held_day(store, day)

    def from_held() -> tuple[np.ndarray, Day]:
        assert held is not None
        data, attrs = held
        field_ = on_model_grid(
            data["precip"].values, data["latitude"].values, data["longitude"].values, grid, None
        )
        missing = int(np.count_nonzero(~np.isfinite(grid.to_cells(field_))))
        return field_, Day(day, attrs["product"], attrs["url"], attrs["sha256"], missing)

    def keep(product: str, url: str, data: bytes) -> tuple[np.ndarray, Day]:
        values, latitude, longitude, nodata = read_geotiff(data)
        nodata = nodata if nodata is not None else float(settings()["nodata"])
        field_ = on_model_grid(values, latitude, longitude, grid, nodata)
        missing = int(np.count_nonzero(~np.isfinite(grid.to_cells(field_))))
        info = Day(day, product, url, hashlib.sha256(data).hexdigest(), missing)
        if store is not None:
            _save_day(store, info, *crop(values, latitude, longitude), nodata)
        return field_, info

    def from_chc() -> tuple[np.ndarray, Day]:
        return _from_chc(day, server, held, keep, from_held)

    def from_mirror() -> tuple[np.ndarray, Day] | None:
        """The final product from the open mirror, asked once, when CHC cannot give it."""
        url = mirror_url(day)
        if url is None:
            return None
        try:
            data = server.get(url) if server.get else download(url)
        except (httpx.HTTPError, OSError):
            return None
        if not data:
            return None
        data = bytes(data)
        if not data.startswith((b"CDF", b"\x89HDF")):
            return None
        values, latitude, longitude = read_mirror(data)
        field_ = on_model_grid(values, latitude, longitude, grid, None)
        missing = int(np.count_nonzero(~np.isfinite(grid.to_cells(field_))))
        info = Day(day, "final", url, hashlib.sha256(data).hexdigest(), missing)
        if store is not None:
            _save_day(store, info, *crop(values, latitude, longitude), None)
        return field_, info

    if held and held[1].get("product") == "final":
        return from_held()
    try:
        return from_chc()
    except CHIRPSUnavailable:
        mirrored = from_mirror()
        if mirrored is None:
            raise
        return mirrored


def _from_chc(
    day: date,
    server: Server,
    held: tuple[xr.Dataset, dict] | None,
    keep: Callable[[str, str, bytes], tuple[np.ndarray, Day]],
    from_held: Callable[[], tuple[np.ndarray, Day]],
) -> tuple[np.ndarray, Day]:
    """The day from CHC's own server: listed final, else preliminary, else the copy held,
    else the file at its usual address."""
    listed = False
    for product in PRODUCTS:
        url = server.daily_url(product, day)
        if url is None:
            continue
        listed = True
        if held and held[1].get("product") == product:
            return from_held()
        data = server.fetch(url)
        if data is None:
            continue
        return keep(product, url, data)
    if held:
        return from_held()
    if not listed:
        # No listing names the day (index pages that changed or cannot be read): the file
        # is tried at the address CHC publishes it under (the final product compressed, the
        # preliminary one not), and kept only if it is a raster. When that fails too, the
        # other days of the year are not asked for in this pass.
        if day.year not in server.unaddressed:
            for product, name in zip(PRODUCTS, day_names(day), strict=True):
                url = directory(product, day.year) + name
                data = server.fetch(url)
                if data and (data[:2] == GZIP_MAGIC or data[:4] in TIFF_MAGIC):
                    return keep(product, url, data)
            server.unaddressed.add(day.year)
        raise CHIRPSUnavailable(server.unlisted(day))
    raise CHIRPSUnavailable(f"CHIRPS for {day.isoformat()} is not published yet")


def week_total(
    valid_start: date,
    grid: DomainGrid,
    server: Server | None = None,
    store: Path | None = None,
) -> WeekTotal:
    """The observed Week-2 total (mm) on the model grid for the window starting on
    ``valid_start``; a cell is missing if any of the seven days lacks data there."""
    server = server or Server()
    total = np.zeros(grid.shape)
    days = []
    for day in window_days(valid_start):
        field_, info = fetch_day(day, grid, server, store)
        total += field_
        days.append(info)
    total[~grid.mask] = np.nan
    return WeekTotal(valid_start, total, days)


def to_dataset(week: WeekTotal, grid: DomainGrid) -> xr.Dataset:
    """The documented observation input (precipitation_week2, mm) for verification."""
    start = datetime(week.start.year, week.start.month, week.start.day, tzinfo=timezone.utc)
    end = start + timedelta(days=DAYS)
    return xr.Dataset(
        {
            "precipitation_week2": (
                ("latitude", "longitude"),
                week.values.astype(np.float32),
                {"units": "mm", "long_name": "CHIRPS v2.0 Week-2 total"},
            )
        },
        coords={"latitude": grid.latitude, "longitude": grid.longitude},
        attrs={
            "valid_start": start.isoformat(),
            "valid_end": end.isoformat(),
            "source": "CHIRPS v2.0 daily, " + " and ".join(week.products),
            "licence": settings()["licence"],
        },
    )


def file_name(valid_start: date) -> str:
    return f"chirps_week2_{valid_start.isoformat()}.nc"


__all__ = [
    "CHIRPSUnavailable",
    "Server",
    "WeekTotal",
    "crop",
    "fetch_day",
    "file_name",
    "read_geotiff",
    "to_dataset",
    "week_total",
    "window_complete",
    "window_days",
]
