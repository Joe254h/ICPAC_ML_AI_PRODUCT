"""Reference-format drafts cannot carry the original bulletin's weather forward."""

import io
import zipfile
from xml.etree import ElementTree

import numpy as np
import pytest
import xarray as xr
from PIL import Image

from climate_engine.cartography import icpac_maps as maps
from climate_engine.products import weekly_bulletin as weekly
from climate_engine.products.bulletin import (
    DEFAULT_TEMPLATE,
    IMAGE_SLOTS,
    REFERENCE_SHA256,
    BulletinInputs,
    MissingDependency,
    WordTemplateGenerator,
)
from climate_engine.provenance import file_checksum


@pytest.fixture
def inputs(tmp_path):
    facts = {
        "valid_start": "2026-10-15T00:00:00+00:00",
        "valid_end": "2026-10-22T00:00:00+00:00",
        "method": {"label": "MBC + ATMOS37 CATBOOST"},
        "model": {"model_id": "reviewed_candidate", "status": "candidate"},
        "input": {"synthetic": True},
        "countries": [
            {
                "country": "Somalia",
                "hybrid_mean_mm": 47.6,
                "hybrid_median_mm": 48.5,
                "hybrid_min_mm": 3.3,
                "hybrid_max_mm": 119.3,
            },
            {"country": "Kenya", "hybrid_mean_mm": 64.3},
        ],
    }
    xr.Dataset(
        {"hybrid": (("latitude", "longitude"), np.full((3, 3), 64.3))},
        coords={"latitude": [-1.0, 0.0, 1.0], "longitude": [36.0, 37.0, 38.0]},
    ).to_netcdf(tmp_path / "forecast.nc")
    return BulletinInputs(
        tmp_path, "w2-2026-10-08-12345678", facts, {}, tmp_path / "countries.csv", {}
    )


def test_word_draft_preserves_template_and_replaces_all_weather_slots(inputs, monkeypatch):
    png = io.BytesIO()
    Image.new("RGB", (32, 32), "#00ff00").save(png, format="PNG")
    monkeypatch.setattr(weekly, "rainfall_png", lambda *args, **kwargs: png.getvalue())
    generator = WordTemplateGenerator()
    assert generator.status()["status"] == "ready"
    result = generator.render_bytes(inputs)
    with (
        zipfile.ZipFile(DEFAULT_TEMPLATE) as reference,
        zipfile.ZipFile(io.BytesIO(result)) as output,
    ):
        assert output.namelist() == reference.namelist()
        for part in reference.namelist():
            if part not in IMAGE_SLOTS and part != "word/document.xml":
                assert output.read(part) == reference.read(part), part
        document = ElementTree.fromstring(output.read("word/document.xml"))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        text = "".join(t.text or "" for t in document.findall(".//w:t", ns))
        assert "Weekly Forecast for 15-21 October 2026" in text
        assert "64.3 mm" in text and "47.6 mm" in text
        assert "DRAFT - NOT APPROVED" in text and "NOT A FORECAST OF REAL WEATHER" in text
        assert "95th-percentile thresholds" in text and "Unavailable" in text
        assert "06-13 October 2026" not in text
        assert "Warmer than average temperatures expected" not in text
        assert "northern parts of Somalia and southeastern parts of Ethiopia" not in text
        for part in IMAGE_SLOTS:
            assert output.read(part) != reference.read(part)
            with Image.open(io.BytesIO(output.read(part))) as image:
                image.verify()
        original = ElementTree.fromstring(reference.read("word/document.xml"))
        generated_section = document.find(".//w:sectPr", ns)
        original_section = original.find(".//w:sectPr", ns)
        assert generated_section is not None and original_section is not None
        assert ElementTree.tostring(generated_section) == ElementTree.tostring(original_section)
    assert file_checksum(DEFAULT_TEMPLATE) == REFERENCE_SHA256


def test_unmapped_or_missing_template_cannot_be_used(inputs, tmp_path):
    missing = WordTemplateGenerator(tmp_path / "missing.docx")
    assert missing.status()["status"] == "unavailable"
    different = tmp_path / "other.docx"
    different.write_bytes(b"unknown document")
    with pytest.raises(MissingDependency, match="field mapping"):
        WordTemplateGenerator(different).render_bytes(inputs)


def test_rainfall_legend_matches_reference_classes():
    style = maps.STYLES["rainfall"]
    assert style.levels is not None and style.palette is not None
    norm = maps.colors.BoundaryNorm(style.levels, len(style.palette))
    cmap = maps.colors.ListedColormap(style.palette)
    values = [0.5, 5.0, 20.0, 40.0, 75.0, 150.0, 250.0, 800.0]
    expected = [
        "#d9d9d9",
        "#ffa500",
        "#ffff00",
        "#caff70",
        "#00ff00",
        "#66cd00",
        "#228b22",
        "#228b22",
    ]
    assert [maps.colors.to_hex(cmap(norm(value))) for value in values] == expected
    assert maps.limits(np.array([1.0, 10.0]), style) == maps.limits(np.array([100.0, 800.0]), style)
    assert weekly.FORMAT_VERSION == "icpac-weekly-v1"


def test_period_uses_exclusive_end_and_missing_products_stay_explicit(inputs):
    assert weekly.valid_period(inputs) == "15-21 October 2026"
    sections = {s["key"]: s for s in weekly.sections(inputs)}
    assert "95th-percentile" in sections["exceptional"]["text"][0]
    for key in ("anomaly", "exceptional", "temperature", "temperature_anomaly", "heat_stress"):
        assert sections[key]["missing_dependency"]
        assert not sections[key].get("map_layer")


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
