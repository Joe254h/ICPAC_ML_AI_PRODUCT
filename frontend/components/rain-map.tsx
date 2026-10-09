"use client";
/**
 * A rainfall field on an interactive map: a light or dark basemap, the field as a
 * transparent Web Mercator overlay rendered by the backend, and the ICPAC country outlines
 * with a hover label. Controls (layer switch, legend) are passed as children and float
 * over the map.
 */
import maplibregl from "maplibre-gl";
import type { ImageSource, MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

export type Bounds = [number, number, number, number];

const ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>';

function basemap(theme: "light" | "dark") {
  const style = theme === "dark" ? "dark_all" : "rastertiles/voyager";
  return {
    version: 8 as const,
    sources: {
      carto: {
        type: "raster" as const,
        tiles: ["a", "b", "c", "d"].map(
          (s) => `https://${s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}.png`,
        ),
        tileSize: 256,
        attribution: ATTRIBUTION,
      },
    },
    layers: [
      {
        id: "background",
        type: "background" as const,
        paint: {
          "background-color": theme === "dark" ? "#0e1a24" : "#aad3f7",
        },
      },
      { id: "carto", type: "raster" as const, source: "carto" },
    ],
  };
}

function corners(bounds: Bounds) {
  const [w, s, e, n] = bounds;
  return [
    [w, n],
    [e, n],
    [e, s],
    [w, s],
  ] as [[number, number], [number, number], [number, number], [number, number]];
}

export default function RainMap({
  overlay,
  bounds,
  hover,
  theme = "light",
  height,
  className,
  credit,
  padding = { west: 6, east: 6, south: 1, north: 1 },
  fitPadding,
  children,
}: {
  /** The overlay image (API path, without /api). */
  overlay: string;
  bounds: Bounds;
  /** Hover text for a country, or null for none. */
  hover?: (country: string) => string | null;
  theme?: "light" | "dark";
  height?: number | string;
  className?: string;
  credit?: string;
  /** Extra degrees shown around the data on each side. */
  padding?: { west: number; east: number; south: number; north: number };
  /** Screen space (px) kept free around the data, e.g. for a panel over the map. */
  fitPadding?: { top: number; bottom: number; left: number; right: number };
  children?: React.ReactNode;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const hoverRef = useRef(hover);
  const first = useRef(overlay);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    hoverRef.current = hover;
  }, [hover]);

  useEffect(() => {
    if (!container.current) return;
    let instance: maplibregl.Map;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        style: basemap(theme),
        bounds: [
          [bounds[0] - padding.west, bounds[1] - padding.south],
          [bounds[2] + padding.east, bounds[3] + padding.north],
        ],
        fitBoundsOptions: fitPadding ? { padding: fitPadding } : undefined,
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
        compact: true,
        customAttribution: credit,
      }),
      "bottom-right",
    );
    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 12,
      className: "rain-popup",
    });
    instance.on("load", () => {
      instance.addSource("field", {
        type: "image",
        url: "/api" + first.current,
        coordinates: corners(bounds),
      });
      instance.addLayer({
        id: "field",
        type: "raster",
        source: "field",
        paint: {
          "raster-opacity": theme === "dark" ? 0.92 : 0.88,
          "raster-resampling": "nearest",
          "raster-fade-duration": 250,
        },
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
        paint: {
          "line-color": theme === "dark" ? "#f4f1e8" : "#2b2f33",
          "line-width": theme === "dark" ? 0.9 : 1.1,
          "line-opacity": theme === "dark" ? 0.75 : 1,
        },
      });
      instance.on("mousemove", "country-hit", (event: MapLayerMouseEvent) => {
        const name = event.features?.[0]?.properties?.name as
          | string
          | undefined;
        const text = name ? hoverRef.current?.(name) : null;
        if (!name || !text) {
          popup.remove();
          return;
        }
        instance.getCanvas().style.cursor = "pointer";
        popup
          .setLngLat(event.lngLat)
          .setHTML(`<strong>${name}</strong><span>${text}</span>`)
          .addTo(instance);
      });
      instance.on("mouseleave", "country-hit", () => {
        instance.getCanvas().style.cursor = "";
        popup.remove();
      });
    });
    instance.on("error", (event) => {
      if (String(event.error?.message ?? "").includes("field")) setFailed(true);
    });
    return () => {
      popup.remove();
      instance.remove();
      map.current = null;
    };
    // The map is built once per extent and theme; the overlay is swapped below.
  }, [bounds[0], bounds[1], bounds[2], bounds[3], theme]);

  useEffect(() => {
    first.current = overlay;
    const source = map.current?.getSource("field") as ImageSource | undefined;
    if (source)
      source.updateImage({
        url: "/api" + overlay,
        coordinates: corners(bounds),
      });
  }, [overlay]);

  return (
    <div
      className={["map-shell", theme === "dark" && "dark", className]
        .filter(Boolean)
        .join(" ")}
      style={height !== undefined ? { height } : undefined}
    >
      <div ref={container} style={{ position: "absolute", inset: 0 }} />
      {children}
      {failed && (
        <div className="map-failed" role="alert">
          The interactive map could not load. The map images on the forecast
          page remain available.
        </div>
      )}
    </div>
  );
}

/** A horizontal colour legend: one swatch per class. */
export function LegendBar({
  title,
  classes,
  unit,
}: {
  title: string;
  classes: [string, string][];
  unit?: string;
}) {
  return (
    <div className="legend-bar">
      <div className="legend-bar-title">
        {title}
        {unit && <span> ({unit})</span>}
      </div>
      <div className="legend-bar-row">
        {classes.map(([colour, label]) => (
          <div key={label} className="legend-bar-class">
            <span style={{ background: colour }} />
            <small>{label}</small>
          </div>
        ))}
      </div>
    </div>
  );
}
