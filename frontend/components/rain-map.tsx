"use client";
/**
 * A rainfall field on an interactive map: a light or dark basemap, the field as a
 * transparent Web Mercator overlay rendered by the backend, everything outside the member
 * states masked, and the ICPAC country outlines with a hover label. Controls (layer switch, legend) are passed as children and float
 * over the map; those marked ``data-map-reserve`` keep their part of the map clear, so they
 * never cover the data.
 */
import maplibregl from "maplibre-gl";
import type {
  ImageSource,
  MapLayerMouseEvent,
  StyleSpecification,
} from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

export type Bounds = [number, number, number, number];

const ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>';

/** CARTO's basemap key (free, https://carto.com/basemaps/apikey/): CARTO serves its raster
 * tiles only with a key since 25 September 2026. Set at build time on Vercel. */
const CARTO_KEY = process.env.NEXT_PUBLIC_CARTO_KEY ?? "";

/** The light or dark basemap: CARTO's raster tiles with the key, else CARTO's vector style
 * (served without a key for now). */
function basemap(theme: "light" | "dark"): string | StyleSpecification {
  if (!CARTO_KEY)
    return `https://basemaps.cartocdn.com/gl/${
      theme === "dark" ? "dark-matter" : "voyager"
    }-gl-style/style.json`;
  const style = theme === "dark" ? "dark_all" : "rastertiles/voyager";
  return {
    version: 8,
    sources: {
      carto: {
        type: "raster",
        tiles: ["a", "b", "c", "d"].map(
          (s) =>
            `https://${s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}.png?key=${encodeURIComponent(CARTO_KEY)}`,
        ),
        tileSize: 256,
        attribution: ATTRIBUTION,
      },
    },
    layers: [
      {
        id: "background",
        type: "background",
        paint: {
          "background-color": theme === "dark" ? "#0c1a14" : "#aad3f7",
        },
      },
      { id: "carto", type: "raster", source: "carto" },
    ],
  };
}

/** OpenStreetMap's own tiles, if CARTO's style cannot be loaded at all. */
function fallbackBasemap(): StyleSpecification {
  return {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        maxzoom: 19,
        attribution:
          '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  };
}

type Padding = { top: number; bottom: number; left: number; right: number };
type Side = keyof Padding;
const NO_PADDING: Padding = { top: 12, bottom: 12, left: 12, right: 12 };
/** Pixels between the data and a panel or legend. */
const GAP = 16;

/** Web Mercator northing in degrees, to compare the data's on-screen width and height. */
const mercator = (lat: number) =>
  (Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) * 180) / Math.PI;

/**
 * The screen space kept free around the data so that nothing floating over the map covers
 * it. Each child marked ``data-map-reserve="right bottom"`` reserves one of the sides it
 * names: the one that leaves the data the largest (a legend at the bottom right takes the
 * right of a wide map and the bottom of a narrow one).
 */
function freeSpace(
  shell: HTMLElement,
  extent: [[number, number], [number, number]],
  base: Padding,
): Padding {
  const box = shell.getBoundingClientRect();
  const [[west, south], [east, north]] = extent;
  const width = east - west;
  const height = mercator(north) - mercator(south);
  const scale = (p: Padding) =>
    Math.min(
      (box.width - p.left - p.right) / width,
      (box.height - p.top - p.bottom) / height,
    );
  const padding = { ...base };
  for (const element of shell.querySelectorAll<HTMLElement>(
    "[data-map-reserve]",
  )) {
    const r = element.getBoundingClientRect();
    if (!r.width || !r.height) continue; // hidden at this width
    const need: Padding = {
      left: r.right - box.left + GAP,
      right: box.right - r.left + GAP,
      top: r.bottom - box.top + GAP,
      bottom: box.bottom - r.top + GAP,
    };
    const sides = (element.dataset.mapReserve ?? "")
      .split(/\s+/)
      .filter((side): side is Side => side in need);
    let best: Padding | null = null;
    for (const side of sides) {
      const tried = {
        ...padding,
        [side]: Math.max(padding[side], need[side]),
      };
      if (!best || scale(tried) > scale(best)) best = tried;
    }
    if (best) Object.assign(padding, best);
  }
  // Panels larger than the map itself: keep at least 40% of each direction for the data.
  const limit = (a: Side, b: Side, total: number) => {
    const sum = padding[a] + padding[b];
    if (sum > total * 0.6) {
      padding[a] *= (total * 0.6) / sum;
      padding[b] *= (total * 0.6) / sum;
    }
  };
  limit("left", "right", box.width);
  limit("top", "bottom", box.height);
  return padding;
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
  padding = { west: 0.5, east: 0.5, south: 0.5, north: 0.5 },
  fitPadding = NO_PADDING,
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
  /** The least screen space (px) kept free around the data, e.g. where something outside
   * the map overlaps it; panels and legends over the map add their own (``data-map-reserve``). */
  fitPadding?: Padding;
  children?: React.ReactNode;
}) {
  const shell = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const hoverRef = useRef(hover);
  const first = useRef(overlay);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    hoverRef.current = hover;
  }, [hover]);

  useEffect(() => {
    if (!container.current || !shell.current) return;
    const frame = shell.current;
    const extent: [[number, number], [number, number]] = [
      [bounds[0] - padding.west, bounds[1] - padding.south],
      [bounds[2] + padding.east, bounds[3] + padding.north],
    ];
    let instance: maplibregl.Map;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        style: basemap(theme),
        bounds: extent,
        fitBoundsOptions: {
          padding: freeSpace(frame, extent, fitPadding),
        },
        attributionControl: false,
        dragRotate: false,
        cooperativeGestures: true,
      });
    } catch {
      setFailed(true);
      return;
    }
    map.current = instance;
    // Refit when the map or a panel over it changes size (a resized window, a legend with
    // other classes), until the reader moves the map themselves.
    let moved = false;
    let pending = 0;
    instance.on("movestart", (event) => {
      if ((event as { originalEvent?: Event }).originalEvent) moved = true;
    });
    const refit = () => {
      cancelAnimationFrame(pending);
      pending = requestAnimationFrame(() => {
        if (moved || !frame.isConnected) return;
        instance.resize();
        instance.fitBounds(extent, {
          padding: freeSpace(frame, extent, fitPadding),
          animate: false,
        });
      });
    };
    const watcher = new ResizeObserver(refit);
    watcher.observe(frame);
    for (const element of frame.querySelectorAll("[data-map-reserve]"))
      watcher.observe(element);
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
    // The credits the basemap and data licences require stay one click away behind the
    // small (i) button, and in the footer; they do not cover the map.
    const collapse = () => {
      const credits = frame.querySelector(".maplibregl-ctrl-attrib");
      credits?.classList.remove("maplibregl-compact-show");
      credits?.removeAttribute("open");
    };
    instance.on("load", collapse);
    instance.on("resize", collapse);
    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 12,
      className: "rain-popup",
    });
    let fellBack = false;
    // The forecast and the outlines go on as soon as a style is ready (not after every
    // basemap tile has arrived), and again if the basemap is swapped for the fallback.
    instance.on("style.load", () => {
      if (instance.getSource("field")) return;
      // Under the basemap's labels when it has them (CARTO's vector style).
      const labels = instance
        .getStyle()
        .layers.find((layer) => layer.type === "symbol")?.id;
      instance.addSource("field", {
        type: "image",
        url: "/api" + first.current,
        coordinates: corners(bounds),
      });
      instance.addLayer(
        {
          id: "field",
          type: "raster",
          source: "field",
          paint: {
            "raster-opacity": theme === "dark" ? 0.92 : 0.88,
            "raster-resampling": "nearest",
            "raster-fade-duration": 250,
          },
        },
        labels,
      );
      // Everything outside the eleven member states is covered, so only the region's
      // rainfall shows (scripts/build_region_mask.py).
      instance.addSource("outside", {
        type: "geojson",
        data: "/icpac-outside.geojson",
      });
      instance.addLayer(
        {
          id: "outside",
          type: "fill",
          source: "outside",
          paint: {
            "fill-color": theme === "dark" ? "#0c1a14" : "#eef1f3",
            "fill-opacity": theme === "dark" ? 0.86 : 0.9,
            "fill-antialias": false,
          },
        },
        // Over the basemap's labels too: place names outside the region are hidden.
      );
      instance.addSource("countries", {
        type: "geojson",
        data: "/icpac-countries.geojson",
      });
      instance.addLayer(
        {
          id: "country-hit",
          type: "fill",
          source: "countries",
          paint: { "fill-color": "#000", "fill-opacity": 0 },
        },
        labels,
      );
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
    });
    instance.on("mousemove", "country-hit", (event: MapLayerMouseEvent) => {
      const name = event.features?.[0]?.properties?.name as string | undefined;
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
    // The basemap style did not load, or is slow to: use OpenStreetMap's tiles instead, so
    // the forecast (added once a style has loaded) never waits on the basemap.
    const fallBack = () => {
      if (fellBack || instance.isStyleLoaded()) return;
      fellBack = true;
      instance.setStyle(fallbackBasemap());
    };
    const slow = window.setTimeout(fallBack, 8000);
    instance.on("error", (event) => {
      if (String(event.error?.message ?? "").includes("field")) setFailed(true);
      else if (!instance.loaded()) fallBack();
    });
    return () => {
      window.clearTimeout(slow);
      watcher.disconnect();
      cancelAnimationFrame(pending);
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
      ref={shell}
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
