"""Weekly forecasts follow the supplied ICPAC bulletin: its sections, wording and maps."""

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import pytest
import xarray as xr
from PIL import Image

from climate_engine.cartography import icpac_maps as maps
from climate_engine.cartography import weekly_maps
from climate_engine.products import weekly_bulletin as weekly
from climate_engine.products.bulletin import (
    DEFAULT_TEMPLATE,
    IMAGE_SLOTS,
    REFERENCE_SHA256,
    BulletinInputs,
    MissingDependency,
    WordTemplateGenerator,
    fill_paragraph,
)
from climate_engine.provenance import file_checksum

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def facts(**changes) -> dict:
    return {
        "valid_start": "2026-10-15T00:00:00+00:00",
        "valid_end": "2026-10-22T00:00:00+00:00",
        "method": {"label": "MBC + ATMOS37 CATBOOST"},
        "model": {"model_id": "reviewed_candidate", "status": "candidate"},
        "input": {"synthetic": True},
        "countries": [],
        **changes,
    }


@pytest.fixture
def inputs(tmp_path):
    """Kenya light; Somalia heavy north of 8 N and moderate elsewhere (0.1 degree grid)."""
    lat = np.round(np.arange(-2.0, 12.01, 0.1), 3)
    lon = np.round(np.arange(38.0, 52.01, 0.1), 3)
    lat2, lon2 = np.meshgrid(lat, lon, indexing="ij")
    masks = weekly.country_masks(weekly.Grid(np.zeros(lat2.shape), lat, lon))
    values = np.full(lat2.shape, np.nan)
    values[masks["Kenya"]] = 20.0
    values[masks["Somalia"]] = np.where(lat2[masks["Somalia"]] > 8.0, 250.0, 80.0)
    xr.Dataset(
        {name: (("latitude", "longitude"), values) for name in ("hybrid", "mbc", "raw")},
        coords={"latitude": lat, "longitude": lon},
    ).to_netcdf(tmp_path / "forecast.nc")
    return BulletinInputs(
        tmp_path, "w2-2026-10-08-12345678", facts(), {}, tmp_path / "countries.csv", {}
    )


def paragraphs(document: bytes) -> list[list[tuple[str, bool]]]:
    """Each paragraph's runs as (text, bold)."""
    root = ElementTree.fromstring(document)
    result = []
    for paragraph in root.iter(W + "p"):
        runs = []
        for run in paragraph.iter(W + "r"):
            text = "".join(t.text or "" for t in run.iter(W + "t"))
            bold = run.find(f"{W}rPr/{W}b") is not None
            if text:
                runs.append((text, bold))
        result.append(runs)
    return result


def test_weeks_are_named_by_their_boundary_dates_as_in_the_reference(inputs):
    # The reference's "06-13 October 2026" is 06 00 UTC to 13 00 UTC (hours 168-336).
    assert weekly.valid_period(inputs) == "15-22 October 2026"
    assert weekly.map_period(inputs) == "15-22 Oct 2026"
    assert weekly.period_label("2026-09-29T00:00:00", "2026-10-06T00:00:00") == (
        "29 September-06 October 2026"
    )
    assert weekly.period_label("2026-12-29T00:00:00", "2027-01-05T00:00:00", "%b") == (
        "29 Dec 2026-05 Jan 2027"
    )
    assert weekly.FORMAT_VERSION == "icpac-weekly-v2"


def test_rainfall_bullets_use_the_reference_wording_and_the_forecast_grid(inputs):
    sections = {s["key"]: s for s in weekly.sections(inputs)}
    rainfall = sections["rainfall"]
    assert rainfall["leads"] == [
        "Heavy rainfall (above 200 mm)",
        "Moderate rainfall (50-200 mm)",
        "Light rainfall (less than 50 mm)",
    ]
    heavy, moderate, light = rainfall["text"]
    assert heavy == "Heavy rainfall (above 200 mm) expected over northern parts of Somalia."
    assert moderate == "Moderate rainfall (50-200 mm) expected over most parts of Somalia."
    assert light == "Light rainfall (less than 50 mm) expected over most parts of Kenya."
    assert sections["headline"]["text"][0] == heavy
    somalia = sections["somalia"]
    assert somalia["leads"] == [
        "Heavy rainfall of above 200mm",
        "Moderate rainfall",
        "Light rainfall",
    ]
    assert (
        somalia["text"][0]
        == "Heavy rainfall of above 200mm expected over northern parts of Somalia."
    )
    assert somalia["text"][2] == "Light rainfall not expected over Somalia."
    assert somalia["map_country"] == "Somalia"


def test_products_this_forecast_lacks_keep_their_place_and_infer_nothing(inputs):
    sections = {s["key"]: s for s in weekly.sections(inputs)}
    for key in ("anomaly", "exceptional", "temperature", "temperature_anomaly", "heat_stress"):
        section = sections[key]
        assert section["missing_dependency"] and not section.get("map_layer")
        assert all("in progress" in text for text in section["text"])
    assert sections["anomaly"]["leads"] == ["More than usual rainfall", "Less than usual rainfall"]
    assert sections["temperature"]["leads"][0] == "Elevated temperatures"
    assert sections["decision_support"]["leads"] == ["Decision-Support Note:"]


@pytest.mark.parametrize(
    "lat, lon, expected",
    [
        ((8.0, 10.0), (8.0, 10.0), "northeastern"),
        ((8.0, 10.0), (0.0, 10.0), "northern"),
        ((0.0, 5.0), (8.0, 10.0), "central to southeastern"),
        ((0.0, 10.0), (0.0, 10.0), None),
        ((0.0, 2.0), (0.0, 10.0), "southern"),
    ],
)
def test_direction_names_where_in_a_country_the_cells_lie(lat, lon, expected):
    grid = np.linspace(0, 10, 41)
    country_lat, country_lon = (a.ravel() for a in np.meshgrid(grid, grid, indexing="ij"))
    inside = (
        (country_lat >= lat[0])
        & (country_lat <= lat[1])
        & (country_lon >= lon[0])
        & (country_lon <= lon[1])
    )
    found = weekly.direction(country_lat[inside], country_lon[inside], country_lat, country_lon)
    assert found == expected


def test_place_phrases_follow_the_reference_style():
    areas = [
        weekly.Area("South Sudan", 0.8, None),
        weekly.Area("Ethiopia", 0.4, "northern"),
        weekly.Area("Uganda", 0.1, "western"),
        weekly.Area("Somalia", 0.05, "southern"),
    ]
    assert weekly.place_phrase(areas) == (
        "most parts of South Sudan, northern parts of Ethiopia and isolated areas in both "
        "western Uganda and southern Somalia"
    )


def test_word_draft_keeps_the_template_and_its_bold_leads(inputs, monkeypatch):
    png = io.BytesIO()
    Image.new("RGB", (64, 64), "#00ff00").save(png, format="PNG")
    monkeypatch.setattr(weekly, "rainfall_png", lambda *args, **kwargs: png.getvalue())
    monkeypatch.setattr(weekly_maps, "render", lambda *args, **kwargs: png.getvalue())
    generator = WordTemplateGenerator()
    assert generator.status()["status"] == "ready"
    result = generator.render_bytes(inputs)
    with (
        zipfile.ZipFile(DEFAULT_TEMPLATE) as reference,
        zipfile.ZipFile(io.BytesIO(result)) as output,
    ):
        assert output.namelist() == reference.namelist()
        for part in reference.namelist():
            if part not in IMAGE_SLOTS and part not in {"word/document.xml", "word/header1.xml"}:
                assert output.read(part) == reference.read(part), part
        document = output.read("word/document.xml")
        runs = paragraphs(document)
        text = ["".join(t for t, _ in p) for p in runs]
        assert "Weekly Forecast for 15-22 October 2026" in text
        heavy = text.index("Heavy rainfall (above 200 mm) expected over northern parts of Somalia.")
        assert runs[heavy][0] == ("Heavy rainfall (above 200 mm)", True)
        assert runs[heavy][1] == (" expected over northern parts of Somalia.", False)
        exceptional = next(p for p in runs if "".join(t for t, _ in p).startswith("Rainfall exc"))
        assert [t for t, bold in exceptional if bold] == [
            "Rainfall exceeding the 95",
            "th",
            " percentile",
        ]
        assert b"superscript" in document
        joined = " ".join(text)
        for old in (
            "06-13 October 2026",
            "Warmer than average temperatures expected",
            "northern parts of Somalia and southeastern parts of Ethiopia",
            "Extreme Caution",
        ):
            assert old not in joined
        header = "".join(t for p in paragraphs(output.read("word/header1.xml")) for t, _ in p)
        assert header.startswith("DRAFT - NOT APPROVED · Model reviewed_candidate (candidate)")
        assert "SYNTHETIC TEST INPUT" in header
        for part in IMAGE_SLOTS:
            assert output.read(part) != reference.read(part)
            with (
                Image.open(io.BytesIO(output.read(part))) as image,
                Image.open(io.BytesIO(reference.read(part))) as original,
            ):
                assert image.format == original.format
                assert image.width / image.height == pytest.approx(
                    original.width / original.height, abs=0.01
                )
        sections = [
            ElementTree.fromstring(xml).find(f".//{W}sectPr")
            for xml in (reference.read("word/document.xml"), document)
        ]
        assert sections[0] is not None and sections[1] is not None
        assert ElementTree.tostring(sections[1]) == ElementTree.tostring(sections[0])
    assert file_checksum(DEFAULT_TEMPLATE) == REFERENCE_SHA256


def test_paragraph_filler_keeps_paragraph_and_run_properties():
    document = (
        '<w:p xmlns:w="w" xmlns:w14="x" w14:paraId="AB"><w:pPr><w:jc w:val="center" /></w:pPr>'
        '<w:bookmarkStart w:id="1" w:name="b" /><w:r><w:rPr><w:b w:val="1" /><w:color w:val="1" />'
        '</w:rPr><w:t>Old</w:t></w:r><w:r><w:rPr><w:color w:val="1" /></w:rPr><w:t> text</w:t>'
        "</w:r></w:p>"
    )
    filled = fill_paragraph(document, "AB", [("New & lead", "bold"), (" rest", "regular")])
    assert '<w:jc w:val="center" />' in filled and "<w:bookmarkStart" in filled
    assert re.findall(r"<w:t[^>]*>(.*?)</w:t>", filled) == ["New &amp; lead", " rest"]
    assert filled.count('<w:b w:val="1" />') == 1


def test_unmapped_or_missing_template_cannot_be_used(inputs, tmp_path):
    missing = WordTemplateGenerator(tmp_path / "missing.docx")
    assert missing.status()["status"] == "unavailable"
    different = tmp_path / "other.docx"
    different.write_bytes(b"unknown document")
    with pytest.raises(MissingDependency, match="field mapping"):
        WordTemplateGenerator(different).render_bytes(inputs)


def test_rainfall_classes_match_the_reference_colour_bar():
    scale = weekly_maps.RAINFALL
    assert scale.levels[1:-1] == (1.0, 10.0, 30.0, 50.0, 100.0, 200.0)
    assert scale.colors == (
        "#d8d8d8",
        "#ffa500",
        "#ffff00",
        "#caff70",
        "#00ff00",
        "#66cd00",
        "#228b22",
    )
    style = maps.STYLES["rainfall"]  # the package maps use the same classes
    assert style.levels is not None and style.levels[1:-1] == scale.levels[1:-1]


def dark_lines(png: bytes) -> tuple[np.ndarray, list[int], list[int]]:
    with Image.open(io.BytesIO(png)) as image:
        pixels = np.asarray(image.convert("RGB")).astype(int)
    dark = pixels.sum(axis=2) < 200
    rows = [y for y in range(dark.shape[0]) if dark[y].mean() > 0.3]
    cols = [x for x in range(dark.shape[1]) if dark[:, x].mean() > 0.3]
    return pixels, rows, cols


def test_weekly_maps_reproduce_the_reference_geometry():
    lat = np.arange(-12.0, 24.0, 0.25)
    lon = np.arange(21.0, 52.0, 0.25)
    field = maps.Field("hybrid", np.full((lat.size, lon.size), 60.0), lat, lon)
    png = weekly_maps.render("Total Rainfall (mm) for 15-22 Oct 2026", field, note="DRAFT")
    pixels, rows, cols = dark_lines(png)
    scale = weekly_maps.SCALE
    assert pixels.shape[:2] == (1024 * scale, 1024 * scale)
    left, top, right, bottom = (v * scale for v in weekly_maps.REGION.frame)
    assert any(abs(r - top) <= 2 for r in rows) and any(abs(r - bottom) <= 2 for r in rows)
    assert any(abs(c - left) <= 2 for c in cols) and any(abs(c - right) <= 2 for c in cols)
    # The seal sits inside the frame, top right: IGAD green in its box.
    x0, y0, x1, y1 = (int(v * scale) for v in weekly_maps.REGION.logo)
    box = pixels[y0:y1, x0:x1]
    green = (box[..., 1] > box[..., 0] + 40) & (box[..., 1] > box[..., 2] + 20)
    assert green.mean() > 0.05
    # Mercator: tick spacing grows northwards like the reference's.
    assert weekly_maps.mercator(20.0) - weekly_maps.mercator(15.0) > 5.2
    assert weekly_maps.mercator(5.0) - weekly_maps.mercator(0.0) == pytest.approx(5.013, abs=0.01)


def test_country_and_placeholder_maps_keep_the_layout():
    message = weekly_maps.render("Rainfall Anomalies for 15-22 Oct 2026", message="In progress")
    _, rows, cols = dark_lines(message)
    assert rows and cols  # the frame is drawn without a field
    somalia = weekly_maps.render("Total Rainfall (mm) for 15-22 Oct 2026", country="Somalia")
    _, rows, cols = dark_lines(somalia)
    left, top, right, bottom = (v * weekly_maps.SCALE for v in weekly_maps.SOMALIA.frame)
    assert any(abs(c - left) <= 2 for c in cols) and any(abs(c - right) <= 2 for c in cols)
    kenya = weekly_maps.country_layout(
        next(c for c in maps.load_boundaries(maps.BOUNDARIES) if c.name == "Kenya")
    )
    assert kenya.frame[2] < kenya.bar[0] and kenya.extent[0] < 34.0 < 42.0 < kenya.extent[1]
    with pytest.raises(ValueError, match="Unknown map country"):
        weekly_maps.render("x", country="Atlantis")


def test_fitted_figures_keep_resolution_and_the_reference_aspect():
    source = io.BytesIO()
    Image.new("RGB", (759, 911), "white").save(source, format="PNG")
    generated = io.BytesIO()
    Image.new("RGB", (2048, 2048), "red").save(generated, format="PNG")
    fitted = weekly.fit_reference_figure(source.getvalue(), generated.getvalue(), "GIF")
    with Image.open(io.BytesIO(fitted)) as image:
        assert image.format == "GIF" and image.width == 2048
        assert image.width / image.height == pytest.approx(759 / 911, abs=0.002)


def test_scope_label_names_the_model_status_and_synthetic_input():
    def inputs_with(**changes) -> BulletinInputs:
        return BulletinInputs(Path("p"), "id", facts(**changes), {}, Path("c.csv"), {})

    label = weekly.scope_label(inputs_with())
    assert "not the production model" in label and "SYNTHETIC TEST INPUT" in label
    real = weekly.scope_label(
        inputs_with(model={"model_id": "m", "status": "production"}, input={"synthetic": False})
    )
    assert "not the production model" not in real and "SYNTHETIC" not in real


def test_somalia_logo_is_offshore_and_ticks_match_country_reference():
    canvas = maps.Canvas(use_valid_mask=False, country="Somalia")
    west, east, south, north = canvas.extent
    x, y, width, height = canvas.logo_box
    points = [
        (west + (x + dx) * (east - west), south + (y + dy) * (north - south))
        for dx in (0.0, width / 2, width)
        for dy in (0.0, height / 2, height)
    ]
    assert not any(canvas.clip.contains_point(point) for point in points)
    assert canvas.tick_spacing == 2
