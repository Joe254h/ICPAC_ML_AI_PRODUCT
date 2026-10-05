"use client";
import { useEffect, useRef, useState } from "react";
import maplibregl, {
  GeoJSONSource,
  ExpressionSpecification,
} from "maplibre-gl";
import type { Analysis } from "@/types";
function scale(layer: string): {
  stops: (string | number)[];
  ticks: string[];
  gradient: string;
  label: string;
} {
  if (layer === "anomaly")
    return {
      stops: [-50, "#a46e43", 0, "#f3efc6", 50, "#2d8270"],
      ticks: ["−50", "0", "+50"],
      gradient: "linear-gradient(90deg,#a46e43,#f3efc6,#2d8270)",
      label: "Synthetic-reference anomaly (%)",
    };
  if (["bias", "improvement"].includes(layer))
    return {
      stops: [-20, "#b97855", 0, "#f3efc6", 20, "#2d8270"],
      ticks: ["−20", "0", "+20"],
      gradient: "linear-gradient(90deg,#b97855,#f3efc6,#2d8270)",
      label:
        layer === "bias"
          ? "Forecast − observation (mm)"
          : "Reduction in absolute error (mm)",
    };
  if (layer === "rmse")
    return {
      stops: [0, "#f3efc6", 15, "#62ad92", 30, "#164e63"],
      ticks: ["0", "15", "30+"],
      gradient: "linear-gradient(90deg,#f3efc6,#62ad92,#164e63)",
      label: "Single-case absolute error (mm)",
    };
  return {
    stops: [
      0,
      "#f3efc6",
      25,
      "#c1dcba",
      50,
      "#62ad92",
      80,
      "#2c8276",
      120,
      "#164e63",
    ],
    ticks: ["0", "25", "50", "80", "120+"],
    gradient: "linear-gradient(90deg,#f3efc6,#c1dcba,#62ad92,#2c8276,#164e63)",
    label: "Seven-day rainfall (mm)",
  };
}
function color(layer: string): ExpressionSpecification {
  return [
    "interpolate",
    ["linear"],
    ["get", "value"],
    ...scale(layer).stops,
  ] as ExpressionSpecification;
}
export default function ClimateMap({ analysis }: { analysis: Analysis }) {
  const container = useRef<HTMLDivElement>(null),
    map = useRef<maplibregl.Map | null>(null),
    data = useRef(analysis);
  const [error, setError] = useState("");
  const [renderedCells, setRenderedCells] = useState(0);
  useEffect(() => {
    data.current = analysis;
    if (map.current?.isStyleLoaded()) {
      (map.current.getSource("rain") as GeoJSONSource)?.setData(analysis.map);
      map.current.setPaintProperty(
        "rain",
        "fill-color",
        color(analysis.selection.layer),
      );
    }
  }, [analysis]);
  useEffect(() => {
    if (!container.current) return;
    try {
      const instance = new maplibregl.Map({
        container: container.current,
        style: {
          version: 8,
          sources: {},
          layers: [
            {
              id: "background",
              type: "background",
              paint: { "background-color": "#e9f0eb" },
            },
          ],
        },
        bounds: [
          [21, -12],
          [52, 24],
        ],
        fitBoundsOptions: { padding: 20 },
        attributionControl: false,
        canvasContextAttributes: { preserveDrawingBuffer: true },
      });
      map.current = instance;
      instance.addControl(new maplibregl.NavigationControl(), "top-right");
      instance.addControl(
        new maplibregl.AttributionControl({
          customAttribution:
            "Natural Earth · public domain | Synthetic rainfall",
        }),
      );
      instance.on("idle", () => {
        if (instance.getLayer("rain"))
          setRenderedCells(
            instance.queryRenderedFeatures({ layers: ["rain"] }).length,
          );
      });
      instance.on("error", () =>
        setError(
          "Interactive rendering unavailable; use the PNG map download.",
        ),
      );
      instance.on("load", () => {
        instance.addSource("rain", { type: "geojson", data: data.current.map });
        instance.addLayer({
          id: "rain",
          type: "fill",
          source: "rain",
          paint: {
            "fill-color": color(data.current.selection.layer),
            "fill-opacity": 0.88,
          },
        });
        instance.addSource("countries", {
          type: "geojson",
          data: "/countries.geojson",
        });
        instance.addLayer({
          id: "country-fill",
          type: "fill",
          source: "countries",
          paint: { "fill-color": "#9ea998", "fill-opacity": 0.09 },
        });
        instance.addLayer({
          id: "country-boundaries",
          type: "line",
          source: "countries",
          paint: { "line-color": "#526858", "line-width": 1.2 },
        });
        fetch("/countries.geojson")
          .then((r) => r.json())
          .then((geo) => {
            if (!map.current) return;
            for (const feature of geo.features) {
              const coords = feature.geometry.coordinates.flat(
                feature.geometry.type === "Polygon" ? 1 : 2,
              ) as number[][];
              const xs = coords.map((c) => c[0]),
                ys = coords.map((c) => c[1]);
              const label = document.createElement("span");
              label.className = "country-map-label";
              label.textContent = feature.properties.name;
              new maplibregl.Marker({ element: label })
                .setLngLat([
                  (Math.min(...xs) + Math.max(...xs)) / 2,
                  (Math.min(...ys) + Math.max(...ys)) / 2,
                ])
                .addTo(instance);
            }
          })
          .catch(() =>
            setError("Country labels unavailable; boundaries remain visible."),
          );
      });
      instance.on("click", "rain", (event) => {
        const value = event.features?.[0]?.properties?.value;
        new maplibregl.Popup()
          .setLngLat(event.lngLat)
          .setText(
            "Synthetic cell: " +
              value +
              (data.current.selection.layer === "anomaly" ? " %" : " mm"),
          )
          .addTo(instance);
      });
      const resize = new ResizeObserver(() => instance.resize());
      resize.observe(container.current);
      return () => {
        resize.disconnect();
        instance.remove();
        map.current = null;
      };
    } catch {
      setError(
        "WebGL map unavailable. Download the PNG product to view this map.",
      );
    }
  }, []);
  const legend = scale(analysis.selection.layer);
  return (
    <div className="map-shell">
      <div
        ref={container}
        className="map"
        aria-label="Interactive Greater Horn climate map"
        data-rendered-cells={renderedCells}
      />
      {error && <div className="map-error">{error}</div>}
      <div className="map-caption">
        <strong>GREATER HORN OF AFRICA</strong>
        <span>
          {analysis.selection.layer} · {analysis.provenance.model as string}
        </span>
      </div>
      <div className="map-legend">
        <span>{legend.label}</span>
        <div
          className="legend-gradient"
          style={{ background: legend.gradient }}
        />
        <div className="legend-ticks">
          {legend.ticks.map((t) => (
            <span key={t}>{t}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
