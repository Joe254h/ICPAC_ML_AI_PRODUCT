"use client";
/**
 * Home: this week's outlook first. A full-width live map of the Week-2 forecast with its
 * headline, the key figures, every member state at a glance and the weekly bulletin.
 */
import Link from "next/link";
import { useState } from "react";
import { ArrowRight, FileText, Play } from "lucide-react";
import RainMap, { LegendBar } from "@/components/rain-map";
import {
  FORECAST_CREDIT,
  LAYERS,
  RAIN_CLASSES,
  useForecastHover,
} from "@/components/forecast-map";
import CountryCards from "@/components/country-cards";
import { useApp } from "@/components/shell";
import { LinkButton, Skeleton } from "@/components/ui";
import { day, num, runTime, weekPeriod } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { Loaded } from "@/services/hooks";
import type {
  BulletinStatus,
  ForecastDetail,
  Variant,
} from "@/types/operational";
import { laterModel, layersOf, primaryOf } from "@/features/operational/shared";

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
/** The key figures overlap the bottom of the hero on wide screens; the panel and the
 * legend keep their own space clear (``data-map-reserve``). */
function heroPadding() {
  const width = typeof window === "undefined" ? 1440 : window.innerWidth;
  const bottom = width < 900 ? 16 : 70;
  return { top: 16, bottom, left: 16, right: 16 };
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
  const { current } = useApp();
  const now = detail ? laterModel(detail, current.data) : null;

  if (!detail || !detail.overlay_bounds || !detail.overlays)
    return (
      <section className="outlook-hero still">
        <div className="wrap outlook-inner">
          <div className="outlook-panel" data-map-reserve="left top">
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
          <div className="outlook-panel" data-map-reserve="left top">
            <p className="outlook-eyebrow">
              Week-2 rainfall outlook · days 8–14
            </p>
            <h1>{weekPeriod(detail.valid_start, detail.valid_end)}</h1>
            <p className="outlook-meta">
              ECMWF ensemble of {runTime(detail.initialization)} · issued{" "}
              {day(detail.generation_time)}
            </p>
            {now && (
              <p className="outlook-note">
                Issued by the earlier model. Forecasts are now made by{" "}
                {now.model_name ?? "a newer model"}.{" "}
                <Link href="/data/runs">Run the weekly cycle</Link>
              </p>
            )}
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
                <FileText size={17} /> Read the bulletin
              </LinkButton>
            </div>
          </div>
        </div>
        <div className="outlook-legend" data-map-reserve="right bottom">
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
            {/* The site's own calendar days: the bulletin's title follows ICPAC's template,
                which counts to the closing 00 UTC (15-22 for days 15 to 21). */}
            Weekly bulletin for{" "}
            {weekPeriod(detail.valid_start, detail.valid_end)}
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
    </>
  );
}
