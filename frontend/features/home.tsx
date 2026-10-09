"use client";
/**
 * Home: this week's outlook first. A full-width live map of the Week-2 forecast with its
 * headline, the key figures, every member state at a glance, the weekly bulletin, the
 * latest observed rainfall and the state of the operational chain.
 */
import Link from "next/link";
import { useState } from "react";
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  CircleDashed,
  Clock3,
  CloudRain,
  Cpu,
  FileText,
  Map as MapIcon,
  MessagesSquare,
  Play,
  Satellite,
  Target,
} from "lucide-react";
import RainMap, { LegendBar } from "@/components/rain-map";
import {
  FORECAST_CREDIT,
  LAYERS,
  RAIN_CLASSES,
  useForecastHover,
} from "@/components/forecast-map";
import CountryCards from "@/components/country-cards";
import { LinkButton, Skeleton } from "@/components/ui";
import { day, num, period, weekPeriod } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { Loaded } from "@/services/hooks";
import type {
  BulletinStatus,
  DataSource,
  Dekad,
  ForecastDetail,
  Variant,
} from "@/types/operational";
import type { Bulletin } from "@/types/workflows";
import { layersOf, primaryOf } from "@/features/operational/shared";

function Lead({ text, lead }: { text: string; lead?: string }) {
  if (lead && text.startsWith(lead))
    return (
      <>
        <strong>{lead}</strong>
        {text.slice(lead.length)}
      </>
    );
  return <>{text}</>;
}

function useBulletin(detail?: ForecastDetail) {
  return useApi<BulletinStatus>(
    detail ? `/forecasts/${detail.forecast_id}/bulletin` : null,
  );
}

// ------------------------------------------------------------------ hero

/** Room for the outlook panel: the region sits to its right on wide screens. */
function heroPadding() {
  const width = typeof window === "undefined" ? 1440 : window.innerWidth;
  if (width < 900) return { top: 215, bottom: 140, left: 16, right: 16 };
  const panel = Math.max(0, (width - 1200) / 2) + 24 + 440 + 40;
  return {
    top: 40,
    bottom: 120,
    left: Math.min(panel, width * 0.5),
    right: 70,
  };
}

function OutlookHero({
  latest,
  bulletin,
}: {
  latest: Loaded<ForecastDetail>;
  bulletin: Loaded<BulletinStatus>;
}) {
  const detail = latest.data;
  const [chosen, setChosen] = useState<Variant | null>(null);
  const layer = detail ? (chosen ?? primaryOf(detail)) : "mbc";
  const hover = useForecastHover(
    detail ?? ({ countries: [] } as unknown as ForecastDetail),
    layer,
  );
  const headline = bulletin.data?.sections?.find((s) => s.key === "headline");

  if (!detail || !detail.overlay_bounds || !detail.overlays)
    return (
      <section className="outlook-hero still">
        <div className="wrap outlook-inner">
          <div className="outlook-panel">
            <p className="outlook-eyebrow">
              Week-2 rainfall outlook · days 8–14
            </p>
            {latest.loading ? (
              <>
                <h1>Loading this week&apos;s outlook…</h1>
                <Skeleton height={90} className="dark" />
              </>
            ) : latest.status === 404 ? (
              <>
                <h1>The first forecast is on its way</h1>
                <p className="outlook-text">
                  This week&apos;s outlook appears here as soon as the newest
                  ECMWF ensemble has been downloaded and the forecast issued.
                </p>
                <div className="outlook-actions">
                  <LinkButton href="/data/runs" variant="amber">
                    <Play size={17} /> Run the weekly cycle
                  </LinkButton>
                </div>
              </>
            ) : (
              <>
                <h1>The outlook could not be loaded</h1>
                <p className="outlook-text">
                  The forecast service did not answer. It may be starting up;
                  try again in a minute.
                </p>
                <div className="outlook-actions">
                  <button
                    type="button"
                    className="btn btn-amber"
                    onClick={latest.reload}
                  >
                    Try again
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </section>
    );

  const available = new Set(layersOf(detail));
  return (
    <section className="outlook-hero" aria-label="This week's rainfall outlook">
      <RainMap
        theme="dark"
        overlay={detail.overlays[layer] ?? Object.values(detail.overlays)[0]}
        bounds={detail.overlay_bounds}
        hover={hover}
        credit={FORECAST_CREDIT}
        padding={{ west: 0.5, east: 0.5, south: 0.5, north: 0.5 }}
        fitPadding={heroPadding()}
        className="outlook-map"
      >
        <div className="wrap outlook-inner">
          <div className="outlook-panel">
            <p className="outlook-eyebrow">
              Week-2 rainfall outlook · days 8–14
            </p>
            <h1>{weekPeriod(detail.valid_start, detail.valid_end)}</h1>
            <p className="outlook-meta">
              ECMWF ensemble of {day(detail.initialization)}, 00 UTC · issued{" "}
              {day(detail.generation_time)}
            </p>
            {headline?.text[0] && (
              <p className="outlook-text">
                <Lead text={headline.text[0]} lead={headline.leads?.[0]} />
              </p>
            )}
            <div className="segmented" role="group" aria-label="Forecast layer">
              {LAYERS.map(({ key, short }) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={layer === key}
                  disabled={!available.has(key)}
                  title={available.has(key) ? short : `${short}: in progress`}
                  onClick={() => setChosen(key)}
                >
                  {short}
                  {!available.has(key) && <small>in progress</small>}
                </button>
              ))}
            </div>
            <div className="outlook-actions">
              <LinkButton href="/forecasts" variant="amber">
                Explore the forecast <ArrowRight size={17} />
              </LinkButton>
              <LinkButton href="/bulletin" variant="ghost-light">
                <FileText size={17} /> Weekly bulletin
              </LinkButton>
            </div>
          </div>
        </div>
        <div className="outlook-legend">
          <LegendBar
            title="Week-2 total rainfall"
            unit="mm"
            classes={RAIN_CLASSES.map(([colour, label]) => [
              colour,
              label
                .replace(" mm", "")
                .replace("Below ", "<")
                .replace("Above ", ">")
                .replace(" – ", "–"),
            ])}
          />
        </div>
      </RainMap>
    </section>
  );
}

// ------------------------------------------------------------------ figures

function KeyFigures({ detail }: { detail: ForecastDetail }) {
  const layer = primaryOf(detail);
  const rows = detail.countries.filter((r) => r[layer]);
  const wettest = [...rows].sort(
    (a, b) => (b[layer]?.mean_mm ?? 0) - (a[layer]?.mean_mm ?? 0),
  )[0];
  const peak = [...rows].sort(
    (a, b) => (b[layer]?.max_mm ?? 0) - (a[layer]?.max_mm ?? 0),
  )[0];
  const verified = detail.verification_status === "available";
  const end = new Date(new Date(detail.valid_end).getTime() + 2 * 86_400_000);
  return (
    <section className="figures-band" aria-label="Key figures">
      <div className="wrap figures">
        <div className="figure-tile">
          <span className="figure-label">Regional mean</span>
          <span className="figure-value">
            {num(detail.interpretation.domain_mean_mm[layer])}
            <small>mm</small>
          </span>
          <span className="figure-hint">
            Area average over the eleven member states
          </span>
        </div>
        {wettest && (
          <div className="figure-tile">
            <span className="figure-label">Wettest country</span>
            <span className="figure-value">{wettest.country}</span>
            <span className="figure-hint">
              Mean {num(wettest[layer]?.mean_mm)} mm
            </span>
          </div>
        )}
        {peak && (
          <div className="figure-tile">
            <span className="figure-label">Highest local total</span>
            <span className="figure-value">
              {num(peak[layer]?.max_mm, 0)}
              <small>mm</small>
            </span>
            <span className="figure-hint">In {peak.country}</span>
          </div>
        )}
        <div className="figure-tile">
          <span className="figure-label">Verification</span>
          <span className="figure-value small">
            {verified ? "Verified" : "Awaiting CHIRPS"}
          </span>
          <span className="figure-hint">
            {verified
              ? "Scored against observed rainfall"
              : `Expected from ${day(end.toISOString())}`}
          </span>
        </div>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ countries

function CountryOutlook({ detail }: { detail: ForecastDetail }) {
  return (
    <section className="section">
      <div className="wrap">
        <div className="section-head">
          <div>
            <p className="kicker-text">Member states</p>
            <h2 className="section-title left">Country outlook</h2>
            <p className="section-sub left">
              Mean Week-2 rainfall of each member state, wettest first. Open a
              country for its map and range.
            </p>
          </div>
          <Link className="link-amber" href="/countries">
            All member states <ArrowRight size={15} />
          </Link>
        </div>
        <CountryCards detail={detail} />
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ bulletin

function BulletinPreview({
  detail,
  bulletin,
}: {
  detail: ForecastDetail;
  bulletin: Loaded<BulletinStatus>;
}) {
  const rainfall = bulletin.data?.sections?.find((s) => s.key === "rainfall");
  return (
    <section className="section tinted">
      <div className="wrap bulletin-preview">
        <div>
          <p className="kicker-text">Weekly bulletin</p>
          <h2 className="section-title left">
            {bulletin.data?.title ?? "This week's bulletin"}
          </h2>
          {bulletin.loading && <Skeleton height={160} />}
          {rainfall && (
            <ul className="bullets">
              {rainfall.text.map((text, i) => (
                <li key={i}>
                  <Lead text={text} lead={rainfall.leads?.[i]} />
                </li>
              ))}
            </ul>
          )}
          <p className="muted-text">
            Drafted from this forecast in the ICPAC bulletin&apos;s wording and
            released after forecaster review.
          </p>
          <div className="row-actions">
            <LinkButton href="/bulletin" variant="green">
              Read the bulletin <ArrowRight size={16} />
            </LinkButton>
            <LinkButton href="/bulletins" variant="outline">
              Drafts and review
            </LinkButton>
          </div>
        </div>
        {rainfall?.map && (
          <figure className="bulletin-map">
            {/* The bulletin's own map, as printed in the Word document. */}
            <img
              src={"/api" + rainfall.map}
              alt={`Total rainfall map for ${weekPeriod(detail.valid_start, detail.valid_end)}`}
              loading="lazy"
            />
          </figure>
        )}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ monitoring

const DEKAD_CLASSES: [string, string][] = [
  ["#ffffff", "<1"],
  ["#c0c0c0", "1–5"],
  ["#ff8c00", "5–10"],
  ["#ffff00", "10–25"],
  ["#98fb98", "25–50"],
  ["#00fa9a", "50–100"],
  ["#00ff00", "100–200"],
  ["#006400", ">200"],
];

function ObservedRainfall() {
  const latest = useApi<Dekad>("/monitoring/dekads/latest");
  const dekad = latest.data;
  if (latest.loading) return null;
  const wettest = dekad
    ? [...dekad.countries].sort((a, b) => b.mean_mm - a.mean_mm)[0]
    : undefined;
  return (
    <section className="section">
      <div className="wrap observed">
        <div className="observed-text">
          <p className="kicker-text">Climate monitoring</p>
          <h2 className="section-title left">Observed rainfall</h2>
          {dekad ? (
            <>
              <p className="section-sub left">
                CHIRPS satellite and station rainfall for the latest dekad,{" "}
                <strong>{period(dekad.start, dekad.end)}</strong> (preliminary).
              </p>
              <dl className="observed-figures">
                <div>
                  <dt>Regional mean</dt>
                  <dd>{num(dekad.region.mean_mm)} mm</dd>
                </div>
                {wettest && (
                  <div>
                    <dt>Wettest country</dt>
                    <dd>
                      {wettest.country} · {num(wettest.mean_mm)} mm
                    </dd>
                  </div>
                )}
                <div>
                  <dt>Area below 1 mm</dt>
                  <dd>{Math.round(dekad.region.dry_fraction * 100)}%</dd>
                </div>
                <div>
                  <dt>Percent of normal</dt>
                  <dd>
                    {dekad.region.percent_of_normal != null
                      ? `${dekad.region.percent_of_normal}%`
                      : "In progress"}
                  </dd>
                </div>
              </dl>
              <LinkButton href="/monitoring" variant="green">
                Rainfall monitoring <ArrowRight size={16} />
              </LinkButton>
            </>
          ) : (
            <p className="section-sub left">
              Observed rainfall appears here once the newest CHIRPS dekad has
              been downloaded; the weekly cycle and the daily task fetch it.
            </p>
          )}
        </div>
        {dekad?.overlays && dekad.overlay_bounds && (
          <div className="observed-map">
            <RainMap
              overlay={dekad.overlays.total}
              bounds={dekad.overlay_bounds}
              height={420}
              credit="Observed: CHIRPS, Climate Hazards Center (UCSB)"
              padding={{ west: 1, east: 1, south: 1, north: 1 }}
              hover={(name) => {
                const row = dekad.countries.find((c) => c.country === name);
                return row ? `Mean ${num(row.mean_mm)} mm this dekad` : null;
              }}
            >
              <div className="map-legend-corner">
                <LegendBar
                  title="Dekad total"
                  unit="mm"
                  classes={DEKAD_CLASSES}
                />
              </div>
            </RainMap>
          </div>
        )}
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ pipeline

type StepState = "done" | "waiting" | "progress";

function Pipeline({ detail }: { detail?: ForecastDetail }) {
  const sources = useApi<DataSource[]>("/data/sources");
  const drafts = useApi<Bulletin[]>("/bulletins");
  const dekad = useApi<Dekad>("/monitoring/dekads/latest");
  const ecmwf = sources.data?.find((s) => s.id === "ecmwf")?.latest as
    | { initialization: string; members: number }
    | null
    | undefined;
  const draft = drafts.data?.find((d) => d.forecast_id === detail?.forecast_id);
  const draftText: Record<string, string> = {
    draft: "Draft ready for review",
    under_review: "Under review",
    approved: "Approved",
    published: "Published",
    rejected: "Rejected; a revision is needed",
  };
  const steps: {
    title: string;
    text: string;
    state: StepState;
    href: string;
    icon: typeof Satellite;
  }[] = [
    {
      title: "ECMWF ensemble",
      text: ecmwf
        ? `Run of ${day(ecmwf.initialization)} · ${ecmwf.members} members`
        : "Not downloaded yet",
      state: ecmwf ? "done" : "waiting",
      href: "/data/ecmwf",
      icon: Satellite,
    },
    {
      title: "Week-2 forecast",
      text: detail ? `Issued ${day(detail.generation_time)}` : "Not issued yet",
      state: detail ? "done" : "waiting",
      href: "/forecasts",
      icon: CloudRain,
    },
    {
      title: "Weekly bulletin",
      text: draft ? draftText[draft.status] : "Not drafted yet",
      state:
        draft?.status === "published" ? "done" : draft ? "progress" : "waiting",
      href: "/bulletins",
      icon: FileText,
    },
    {
      title: "Observed rainfall",
      text: dekad.data
        ? `Dekad ${period(dekad.data.start, dekad.data.end)}`
        : "No dekad yet",
      state: dekad.data ? "done" : "waiting",
      href: "/monitoring",
      icon: BarChart3,
    },
    {
      title: "Verification",
      text:
        detail?.verification_status === "available"
          ? "Verified against CHIRPS"
          : "Waits for the week to be observed",
      state: detail?.verification_status === "available" ? "done" : "waiting",
      href: "/verification",
      icon: Target,
    },
    {
      title: "AI/ML layer",
      text: "In progress: needs upper-air inputs",
      state: "progress",
      href: "/forecasts/hybrid",
      icon: Cpu,
    },
  ];
  const Icon = { done: CheckCircle2, waiting: Clock3, progress: CircleDashed };
  return (
    <section className="section tinted">
      <div className="wrap">
        <p className="kicker-text center">Operational chain</p>
        <h2 className="section-title">From the ensemble to the bulletin</h2>
        <p className="section-sub">
          Every step runs in this service and is recorded; the state of each is
          shown live.
        </p>
        <ol className="pipeline">
          {steps.map((step) => {
            const State = Icon[step.state];
            return (
              <li key={step.title} className={step.state}>
                <Link href={step.href}>
                  <span className="pipe-icon">
                    <step.icon size={22} aria-hidden />
                  </span>
                  <strong>{step.title}</strong>
                  <span className="pipe-text">{step.text}</span>
                  <span className="pipe-state">
                    <State size={14} aria-hidden />
                    {step.state === "done"
                      ? "Done"
                      : step.state === "progress"
                        ? "In progress"
                        : "Waiting"}
                  </span>
                </Link>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ products

const PRODUCTS = [
  {
    title: "Week-2 forecast",
    text: "Days 8–14 rainfall for the region and every member state, with its layers and figures.",
    href: "/forecasts",
    icon: CloudRain,
  },
  {
    title: "Rainfall maps",
    text: "The bulletin's maps for the region and each country, ready to download.",
    href: "/maps/rainfall",
    icon: MapIcon,
  },
  {
    title: "Rainfall monitoring",
    text: "Observed rainfall of the latest dekad from CHIRPS, by country.",
    href: "/monitoring",
    icon: BarChart3,
  },
  {
    title: "Verification",
    text: "How each forecast compared with observed rainfall, pooled by season.",
    href: "/verification",
    icon: Target,
  },
  {
    title: "Weekly bulletin",
    text: "The ICPAC bulletin as a Word document and web page, released after review.",
    href: "/bulletin",
    icon: FileText,
  },
  {
    title: "Forecaster Copilot",
    text: "Ask about this week's forecast, or about weather and climate in general.",
    href: "/copilot",
    icon: MessagesSquare,
  },
];

function Products() {
  return (
    <section className="section">
      <div className="wrap">
        <p className="kicker-text center">Products and services</p>
        <h2 className="section-title">Everything in one place</h2>
        <div className="product-grid">
          {PRODUCTS.map(({ title, text, href, icon: Icon }) => (
            <Link key={title} href={href} className="product-card">
              <span className="product-icon">
                <Icon size={24} aria-hidden />
              </span>
              <strong>{title}</strong>
              <span>{text}</span>
              <span className="product-more">
                Open <ArrowRight size={14} />
              </span>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const latest = useApi<ForecastDetail>("/forecasts/latest");
  const bulletin = useBulletin(latest.data);
  return (
    <>
      <OutlookHero latest={latest} bulletin={bulletin} />
      {latest.data && <KeyFigures detail={latest.data} />}
      {latest.data && <CountryOutlook detail={latest.data} />}
      {latest.data && (
        <BulletinPreview detail={latest.data} bulletin={bulletin} />
      )}
      <ObservedRainfall />
      <Pipeline detail={latest.data} />
      <Products />
    </>
  );
}
