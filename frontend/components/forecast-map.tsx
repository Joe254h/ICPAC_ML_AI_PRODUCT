"use client";
/**
 * The Week-2 rainfall forecast on an interactive map, in the manner of ICPAC's Hazards
 * Watch: a basemap, the forecast layer (a Mercator overlay rendered by the backend in the
 * weekly bulletin's rainfall classes), country outlines with their area means, a vertical
 * layer rail on the left and the legend in the lower right.
 */
import maplibregl from "maplibre-gl";
import type { ImageSource, MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { CloudRain, Cpu, Droplets } from "lucide-react";
import { validDays, num } from "@/lib/format";
import type { CountryRow, ForecastDetail, Variant } from "@/types/operational";

export const RAIN_CLASSES: [string, string][] = [
  ["#d8d8d8", "Below 1 mm"],
  ["#ffa500", "1 – 10 mm"],
  ["#ffff00", "10 – 30 mm"],
  ["#caff70", "30 – 50 mm"],
  ["#00ff00", "50 – 100 mm"],
  ["#66cd00", "100 – 200 mm"],
  ["#228b22", "Above 200 mm"],
];

export const LAYERS: {
  key: Variant;
  label: string;
  icon: React.ComponentType<{ size?: number }>;
}[] = [
  { key: "raw", label: "Raw ECMWF", icon: CloudRain },
  { key: "mbc", label: "MBC corrected", icon: Droplets },
  { key: "hybrid", label: "MBC + AI/ML", icon: Cpu },
];

const BASEMAP = {
  version: 8 as const,
  sources: {
    carto: {
      type: "raster" as const,
      tiles: ["a", "b", "c", "d"].map(
        (s) =>
          `https://${s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png`,
      ),
      tileSize: 256,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>',
    },
  },
  layers: [
    {
      id: "background",
      type: "background" as const,
      paint: { "background-color": "#aad3f7" },
    },
    { id: "carto", type: "raster" as const, source: "carto" },
  ],
};

function corners(bounds: [number, number, number, number]) {
  const [w, s, e, n] = bounds;
  return [
    [w, n],
    [e, n],
    [e, s],
    [w, s],
  ] as [[number, number], [number, number], [number, number], [number, number]];
}

export default function ForecastMap({
  detail,
  layer,
  onLayer,
  height,
}: {
  detail: ForecastDetail;
  layer: Variant;
  onLayer: (layer: Variant) => void;
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const rows = useRef<CountryRow[]>(detail.countries);
  const current = useRef(layer);
  const [failed, setFailed] = useState(false);
  const overlay = (key: Variant) => "/api" + (detail.overlays?.[key] ?? "");

  useEffect(() => {
    rows.current = detail.countries;
    current.current = layer;
  }, [detail.countries, layer]);

  useEffect(() => {
    if (!container.current || !detail.overlay_bounds) return;
    const bounds = detail.overlay_bounds;
    let instance: maplibregl.Map;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        style: BASEMAP,
        bounds: [
          [bounds[0] - 6, bounds[1] - 1],
          [bounds[2] + 6, bounds[3] + 1],
        ],
        attributionControl: false,
        dragRotate: false,
        cooperativeGestures: true,
      });
    } catch {
      setFailed(true);
      return;
    }
    map.current = instance;
    instance.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right",
    );
    instance.addControl(
      new maplibregl.AttributionControl({
        compact: false,
        customAttribution: "Forecast: ICPAC · ECMWF Open Data (CC BY 4.0)",
      }),
      "bottom-right",
    );
    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 10,
    });
    instance.on("load", () => {
      instance.addSource("forecast", {
        type: "image",
        url: overlay(current.current),
        coordinates: corners(bounds),
      });
      instance.addLayer({
        id: "forecast",
        type: "raster",
        source: "forecast",
        paint: { "raster-opacity": 0.9, "raster-resampling": "nearest" },
      });
      instance.addSource("countries", {
        type: "geojson",
        data: "/icpac-countries.geojson",
      });
      instance.addLayer({
        id: "country-hit",
        type: "fill",
        source: "countries",
        paint: { "fill-color": "#000", "fill-opacity": 0 },
      });
      instance.addLayer({
        id: "country-line",
        type: "line",
        source: "countries",
        paint: { "line-color": "#2b2f33", "line-width": 1.1 },
      });
      instance.on("mousemove", "country-hit", (event: MapLayerMouseEvent) => {
        const name = event.features?.[0]?.properties?.name as
          | string
          | undefined;
        if (!name) return;
        const row = rows.current.find((r) => r.country === name);
        const stats = row?.[current.current];
        instance.getCanvas().style.cursor = "pointer";
        popup
          .setLngLat(event.lngLat)
          .setHTML(
            `<strong>${name}</strong><br>${
              stats
                ? `Mean ${num(stats.mean_mm)} mm · max ${num(stats.max_mm, 0)} mm`
                : "No statistics"
            }`,
          )
          .addTo(instance);
      });
      instance.on("mouseleave", "country-hit", () => {
        instance.getCanvas().style.cursor = "";
        popup.remove();
      });
    });
    instance.on("error", (event) => {
      if (String(event.error?.message ?? "").includes("forecast"))
        setFailed(true);
    });
    return () => {
      popup.remove();
      instance.remove();
      map.current = null;
    };
    // The map is built once per forecast; layer changes update the overlay below.
  }, [detail.forecast_id, detail.overlay_bounds]);

  useEffect(() => {
    const source = map.current?.getSource("forecast") as
      | ImageSource
      | undefined;
    if (source && detail.overlay_bounds)
      source.updateImage({
        url: overlay(layer),
        coordinates: corners(detail.overlay_bounds),
      });
  }, [layer]);

  const available = new Set(Object.keys(detail.overlays ?? {}));
  return (
    <div className="map-shell" style={height ? { height } : undefined}>
      <div ref={container} style={{ position: "absolute", inset: 0 }} />
      <div className="layer-rail">
        <div className="rail" role="group" aria-label="Forecast layer">
          {LAYERS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              type="button"
              aria-pressed={layer === key}
              aria-label={label}
              title={available.has(key) ? label : `${label}: in progress`}
              disabled={!available.has(key)}
              onClick={() => onLayer(key)}
            >
              <Icon size={20} />
            </button>
          ))}
        </div>
        <div className="labels" aria-hidden>
          {LAYERS.map(({ key, label }) => (
            <span
              key={key}
              className={layer === key ? "on" : available.has(key) ? "" : "off"}
            >
              {label}
              {!available.has(key) && " (in progress)"}
            </span>
          ))}
        </div>
      </div>
      <div className="legend-box">
        <div className="title">Week-2 Total Rainfall</div>
        <div className="sub">
          Valid {validDays(detail.valid_start, detail.valid_end)}
        </div>
        {RAIN_CLASSES.map(([colour, label]) => (
          <div className="row" key={label}>
            <span className="swatch" style={{ background: colour }} />
            {label}
          </div>
        ))}
      </div>
      <div className="map-badge">
        ICPAC
        <b>Week-2</b>
        Forecast
      </div>
      {failed && (
        <div
          className="notice red"
          style={{
            position: "absolute",
            top: 70,
            left: 70,
            right: 70,
            zIndex: 6,
          }}
        >
          The interactive map could not load. The forecast maps below remain
          available.
        </div>
      )}
    </div>
  );
}
