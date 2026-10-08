"""Operational input data: download, decode and reduce to the ICPAC-11 model domain.

Sources in use:

* ``ecmwf_opendata``: ECMWF ensemble (ENS) Week-2 rainfall from ECMWF Open Data;
* ``chirps``: CHIRPS v2.0 daily rainfall, summed over a forecast's Week-2 window, for
  verification.

TAMSAT, RFE2, ARC2 and IMERG are listed in config/data_sources.yaml as planned sources;
they have no reader yet and are shown as such.
"""

from climate_engine.core import config


def sources() -> list[dict]:
    """Every observation and forecast source, with its status (active or planned)."""
    return list(config("data_sources")["sources"])


__all__ = ["sources"]
