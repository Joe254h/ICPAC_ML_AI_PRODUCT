import io
import json
import zipfile
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np
import pytest
import xarray as xr
from PIL import Image

from climate_engine.products import supplemental, supplemental_document
from climate_engine.products.bulletin import DEFAULT_TEMPLATE
from climate_engine.provenance import file_checksum


@pytest.fixture
def reviewed(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    coords = {"latitude": [0.0, 1.0], "longitude": [30.0, 31.0]}
    forecast = xr.Dataset(
        {
            "mbc": (("latitude", "longitude"), np.full((2, 2), 100.0), {"units": "mm"}),
            "domain_mask": (("latitude", "longitude"), [[1, 1], [1, 0]]),
        },
        coords=coords,
    )
    source = tmp_path / "references.nc"
    data = {
        "rainfall_normal": (50.0, "mm"),
        "rainfall_extreme_threshold": (90.0, "mm"),
        "temperature_forecast": (300.0, "K"),
        "temperature_normal": (295.0, "K"),
        "heat_stress": (35.0, "degC"),
    }
    xr.Dataset(
        {
            name: (("latitude", "longitude"), np.full((2, 2), value), {"units": units})
            for name, (value, units) in data.items()
        },
        coords=coords,
    ).to_netcdf(source)
    provenance = {
        "forecast_valid_start": "2026-10-17T00:00:00+00:00",
        "forecast_valid_end": "2026-10-24T00:00:00+00:00",
    }
    manifest: dict[str, Any] = {
        "version": 1,
        "approved_by": "Reviewed test fixture",
        "reference_period": "1991-2020",
        "reference_source": "Synthetic test fixture, not operational data",
        "extreme_definition": "Synthetic fixed threshold, not a validated alert threshold",
        "valid_start": provenance["forecast_valid_start"],
        "valid_end": provenance["forecast_valid_end"],
        "heat_stress_definition": "Synthetic index fixture; not an operational definition",
        "fields": {
            name: {
                "file": str(source),
                "sha256": file_checksum(source),
                "variable": name,
                "units": units,
            }
            for name, (_, units) in data.items()
        },
    }
    manifest["fields"]["temperature_forecast"]["aggregation"] = "week_mean"
    return forecast, provenance, manifest, source


def test_derived_products_use_only_reviewed_exact_window_fields(reviewed):
    forecast, provenance, manifest, _ = reviewed
    output, metadata = supplemental.compute(forecast, "mbc", provenance, manifest)
    assert set(metadata["available"]) == set(supplemental.NAMES)
    assert metadata["pending"] == {}
    assert output.rainfall_anomaly.values[0, 0] == 50.0
    assert output.exceptional_rainfall.values[0, 0] == 1.0
    assert output.mean_temperature.values[0, 0] == pytest.approx(26.85)
    assert output.temperature_anomaly.values[0, 0] == 5.0
    assert output.heat_stress.values[0, 0] == 35.0
    assert np.isnan(output.rainfall_anomaly.values[1, 1])
    assert "not a calibrated event probability" in metadata["notes"][0]


def test_missing_scientific_inputs_stay_explicitly_pending(reviewed):
    forecast, provenance, manifest, _ = reviewed
    manifest["fields"] = {}
    output, metadata = supplemental.compute(forecast, "mbc", provenance, manifest)
    assert not output.data_vars
    assert set(metadata["pending"]) == set(supplemental.NAMES)


@pytest.mark.parametrize(
    "defect", ["window", "checksum", "units", "heat_definition", "outside_root"]
)
def test_reference_contract_rejects_changed_or_incompatible_science(reviewed, tmp_path, defect):
    forecast, provenance, manifest, source = reviewed
    if defect == "window":
        manifest["valid_start"] = "wrong"
    elif defect == "checksum":
        source.write_bytes(source.read_bytes() + b"changed")
    elif defect == "units":
        manifest["fields"]["rainfall_normal"]["units"] = "K"
    elif defect == "heat_definition":
        manifest.pop("heat_stress_definition")
    else:
        manifest["fields"]["rainfall_normal"]["file"] = str(tmp_path.parent / "not-approved.nc")
    with pytest.raises((ValueError, FileNotFoundError)):
        supplemental.compute(forecast, "mbc", provenance, manifest)


def test_reference_artifacts_must_already_match_grid(reviewed):
    forecast, provenance, manifest, source = reviewed
    with xr.open_dataset(source) as opened:
        changed = opened.load().assign_coords(latitude=[1.0, 2.0])
    changed.to_netcdf(source)
    for entry in manifest["fields"].values():
        entry["sha256"] = file_checksum(source)
    with pytest.raises(ValueError, match="exact forecast grid"):
        supplemental.compute(forecast, "mbc", provenance, manifest)


def test_approval_manifest_is_pinned_and_output_is_separate(reviewed, tmp_path, monkeypatch):
    forecast, provenance, manifest, _ = reviewed
    assert (
        supplemental.build(tmp_path / "absent", tmp_path / "output", "mbc")["status"] == "blocked"
    )
    path = tmp_path / "approved.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setenv("WEEKLY_REFERENCE_MANIFEST", str(path))
    with pytest.raises(ValueError, match="checksum"):
        supplemental.approval()
    monkeypatch.setenv("WEEKLY_REFERENCE_MANIFEST_SHA256", file_checksum(path))
    directory = tmp_path / "forecast"
    directory.mkdir()
    forecast["raw"] = forecast["mbc"] * 2
    forecast["raw"].attrs["units"] = "mm"
    forecast.to_netcdf(directory / "forecast.nc")
    (directory / "provenance.json").write_text(json.dumps(provenance))
    before = file_checksum(directory / "forecast.nc")
    built = supplemental.build(directory, tmp_path / "separate-output", "mbc")
    assert built["status"] == "available"
    assert file_checksum(directory / "forecast.nc") == before
    assert (tmp_path / "separate-output" / built["revision"] / "products.nc").is_file()
    first_path = tmp_path / "separate-output" / built["revision"] / "products.nc"
    first_hash = file_checksum(first_path)
    changed_layer = supplemental.build(directory, tmp_path / "separate-output", "raw")
    assert changed_layer["revision"] != built["revision"]
    assert file_checksum(first_path) == first_hash


def test_supplemental_word_maps_and_text_are_embedded_in_a_self_contained_document():
    metadata = {
        "reference_period": "1991-2020",
        "approved_by": "Reviewed fixture",
        "summary": {"rainfall_anomaly": {"mean": 10.0, "min": -2.0, "max": 20.0, "units": "mm"}},
    }
    image = io.BytesIO()
    Image.new("RGB", (20, 10), "green").save(image, format="PNG")
    rendered = supplemental_document.append_document(
        DEFAULT_TEMPLATE.read_bytes(), metadata, {"rainfall_anomaly": image.getvalue()}
    )
    with zipfile.ZipFile(io.BytesIO(rendered)) as package:
        ET.fromstring(package.read("word/document.xml"))
        relationships = ET.fromstring(package.read("word/_rels/document.xml.rels"))
        assert any(r.get("Id") == "rIdSupplemental1" for r in relationships)
        assert package.read("word/media/automation-rainfall_anomaly.png") == image.getvalue()
        assert b"Rainfall anomaly" in package.read("word/document.xml")
        assert b"Reviewed fixture" in package.read("word/document.xml")
    from backend.app.services.bulletin_export import images

    assert images(rendered)["rainfall_anomaly"][1] == image.getvalue()
