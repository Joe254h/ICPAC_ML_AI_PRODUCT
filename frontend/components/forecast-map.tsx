"use client";
/**
 * The Week-2 rainfall forecast on an interactive map, in the manner of ICPAC's Hazards
 * Watch: the forecast layer in the weekly bulletin's rainfall classes, country outlines
 * with their area means, a vertical layer rail on the left and the legend in the lower
 * right.
 */
import { useCallback } from "react";
import { CloudRain, Cpu, Droplets } from "lucide-react";
import RainMap from "@/components/rain-map";
import { validDays, num } from "@/lib/format";
import type { ForecastDetail, Variant } from "@/types/operational";

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
  short: string;
  icon: React.ComponentType<{ size?: number }>;
}[] = [
  { key: "raw", label: "Raw ECMWF", short: "Raw ECMWF", icon: CloudRain },
  { key: "mbc", label: "MBC corrected", short: "MBC", icon: Droplets },
  { key: "hybrid", label: "MBC + AI/ML", short: "MBC + AI/ML", icon: Cpu },
];

export const FORECAST_CREDIT = "Forecast: ICPAC · ECMWF Open Data (CC BY 4.0)";

/** Hover text for a country: its area mean and maximum in the shown layer. */
export function useForecastHover(detail: ForecastDetail, layer: Variant) {
  return useCallback(
    (name: string) => {
      const stats = detail.countries.find((r) => r.country === name)?.[layer];
      return stats
        ? `Mean ${num(stats.mean_mm)} mm · up to ${num(stats.max_mm, 0)} mm`
        : null;
    },
    [detail.countries, layer],
  );
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
  const hover = useForecastHover(detail, layer);
  if (!detail.overlay_bounds || !detail.overlays) return null;
  const available = new Set(Object.keys(detail.overlays));
  return (
    <RainMap
      overlay={detail.overlays[layer] ?? Object.values(detail.overlays)[0]}
      bounds={detail.overlay_bounds}
      hover={hover}
      height={height}
      credit={FORECAST_CREDIT}
    >
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
    </RainMap>
  );
}
