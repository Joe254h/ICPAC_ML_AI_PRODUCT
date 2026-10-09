"use client";
/** Home page, laid out like www.icpac.net. */
import Link from "next/link";
import { useState } from "react";
import {
  Boxes,
  CloudRain,
  Cpu,
  FileText,
  MessagesSquare,
  Satellite,
  SlidersHorizontal,
  Target,
} from "lucide-react";
import { HeroBanner } from "@/components/banner";
import ForecastMap from "@/components/forecast-map";
import { LinkButton, Skeleton, Status } from "@/components/ui";
import { day, dateTime, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type { Loaded } from "@/services/hooks";
import type {
  BulletinStatus,
  DataSource,
  ForecastDetail,
  ForecastRun,
  Variant,
} from "@/types/operational";
import type { Bulletin } from "@/types/workflows";
import {
  NoForecast,
  mapUrl,
  methodName,
  primaryOf,
} from "@/features/operational/shared";

const PRODUCTS = [
  {
    title: "Weekly forecast bulletin",
    text: "The ICPAC weekly bulletin, drafted from the latest forecast as a Word document and a web page, and released after forecaster review.",
    href: "/bulletin",
  },
  {
    title: "Rainfall maps",
    text: "Week-2 total rainfall for the region and each member state, in the bulletin's colour classes: raw ECMWF, MBC and MBC + AI/ML.",
    href: "/maps/rainfall",
  },
  {
    title: "Country outlooks",
    text: "Area means, ranges and maps for each of the eleven ICPAC member states.",
    href: "/countries/kenya",
  },
  {
    title: "Forecast verification",
    text: "Every forecast is scored against CHIRPS once its week has passed: MAE, RMSE, bias and correlation, pooled by season.",
    href: "/verification",
  },
  {
    title: "Forecast archive",
    text: "All issued Week-2 forecasts with their product packages, provenance and verification.",
    href: "/forecasts/archive",
  },
  {
    title: "Forecaster Copilot",
    text: "Ask questions about the current forecast, its maps and its verification; every number comes from the forecast package.",
    href: "/copilot",
  },
];

const WORKFLOW = [
  { title: "ECMWF Ensemble", href: "/data/ecmwf", icon: Satellite },
  { title: "CHIRPS Observations", href: "/data/chirps", icon: CloudRain },
  {
    title: "Bias Correction (MBC)",
    href: "/forecasts/mbc",
    icon: SlidersHorizontal,
  },
  { title: "AI/ML Hybrid", href: "/forecasts/hybrid", icon: Cpu },
  { title: "Forecast Verification", href: "/verification", icon: Target },
  { title: "Weekly Bulletin", href: "/bulletin", icon: FileText },
  { title: "Model Registry", href: "/models", icon: Boxes },
  { title: "Forecaster Copilot", href: "/copilot", icon: MessagesSquare },
];

function Hero({ forecast }: { forecast?: ForecastDetail }) {
  return (
    <HeroBanner>
      <span className="kicker" aria-hidden />
      <h1>Week-2 Rainfall Forecasts for Eastern Africa</h1>
      <p className="lead">
        Days 8–14 rainfall outlooks for the eleven ICPAC member states, from the
        ECMWF ensemble with statistical and AI/ML correction.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 14 }}>
        <LinkButton href="/forecasts" variant="amber">
          View latest forecast
        </LinkButton>
        <LinkButton href="/bulletin" variant="ghost-light">
          Weekly bulletin
        </LinkButton>
      </div>
      {forecast && (
        <div className="hero-facts">
          <span>
            Valid {validDays(forecast.valid_start, forecast.valid_end)}
          </span>
          <span>ECMWF run {day(forecast.initialization)}</span>
          <span>{methodName(forecast)}</span>
        </div>
      )}
    </HeroBanner>
  );
}

function ForecastSection({ latest }: { latest: Loaded<ForecastDetail> }) {
  const [layer, setLayer] = useState<Variant | null>(null);
  const detail = latest.data;
  return (
    <section className="section grey">
      <div className="wrap">
        <h2 className="section-title">Our Week-2 Rainfall Outlook</h2>
        <p className="section-sub">
          Total rainfall expected over days 8–14. Choose a forecast layer on the
          left; hover over a country for its area mean.
        </p>
        {latest.loading && <Skeleton height={640} />}
        {latest.status === 404 && <NoForecast />}
        {detail && (
          <>
            <ForecastMap
              detail={detail}
              layer={layer ?? primaryOf(detail)}
              onLayer={setLayer}
            />
            <p style={{ textAlign: "center", marginTop: 18 }}>
              <Link className="link-amber" href="/forecasts">
                Explore the full forecast →
              </Link>
            </p>
          </>
        )}
      </div>
    </section>
  );
}

function Products() {
  const [active, setActive] = useState(0);
  return (
    <section className="section contours">
      <div className="wrap">
        <h2 className="section-title" style={{ marginBottom: 48 }}>
          Our Products
        </h2>
        <div className="split">
          <div className="globe">
            <img
              src="/images/globe-africa.webp"
              alt="The Earth seen from space, centred on Eastern Africa"
            />
          </div>
          <div className="product-list">
            {PRODUCTS.map((product, index) => (
              <div
                key={product.title}
                className={index === active ? "active" : ""}
              >
                <button
                  type="button"
                  aria-expanded={index === active}
                  onClick={() => setActive(index)}
                >
                  {product.title}
                </button>
                {index === active && (
                  <div className="detail">
                    <p>{product.text}</p>
                    <Link className="link-amber" href={product.href}>
                      Explore More
                    </Link>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function Workflow() {
  return (
    <section className="section white">
      <div className="wrap">
        <h2 className="section-title">How the Forecast Is Made</h2>
        <p className="section-sub">
          From the ECMWF ensemble to a reviewed weekly bulletin, every step runs
          in this service and is recorded.
        </p>
        <div className="areas">
          {WORKFLOW.map(({ title, href, icon: Icon }) => (
            <Link key={title} href={href} className="area">
              <span className="blob">
                <Icon size={54} strokeWidth={1.15} aria-hidden />
              </span>
              {title}
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

type Update = {
  category: string;
  title: string;
  text: string;
  date: string;
  href: string;
  image: string;
  contain?: boolean;
};

function UpdateCard({ update }: { update: Update }) {
  return (
    <article className="update-card">
      <Link
        href={update.href}
        className={update.contain ? "media contain" : "media"}
      >
        <img src={update.image} alt="" loading="lazy" />
      </Link>
      <div className="body">
        <div className="cat">{update.category}</div>
        <h3>
          <Link href={update.href} style={{ color: "inherit" }}>
            {update.title}
          </Link>
        </h3>
        <p>{update.text}</p>
      </div>
      <div className="foot">
        <span>{update.date}</span>
        <Link href={update.href}>Read more</Link>
      </div>
    </article>
  );
}

function LatestUpdates({ detail }: { detail?: ForecastDetail }) {
  const runs = useApi<ForecastRun[]>("/forecasts");
  const drafts = useApi<Bulletin[]>("/bulletins");
  const sources = useApi<DataSource[]>("/data/sources");
  const bulletin = useApi<BulletinStatus>(
    detail ? `/forecasts/${detail.forecast_id}/bulletin` : null,
  );
  const updates: Update[] = [];
  if (detail) {
    const headline = bulletin.data?.sections?.find((s) => s.key === "headline");
    updates.push({
      category: "Forecast",
      title:
        bulletin.data?.title ??
        `Week-2 forecast, ${validDays(detail.valid_start, detail.valid_end)}`,
      text:
        headline?.text[0] ?? `${methodName(detail)} rainfall for days 8–14.`,
      date: day(detail.generation_time),
      href: "/forecasts",
      image: mapUrl(detail, primaryOf(detail)),
      contain: true,
    });
  } else
    updates.push({
      category: "Forecast",
      title: "First Week-2 forecast pending",
      text: "The forecast is issued as soon as the newest ECMWF ensemble has been downloaded and processed.",
      date: "Weekly",
      href: "/data/runs",
      image: "/images/hero-eastern-africa.webp",
    });
  const draft = drafts.data?.[0];
  if (!draft)
    updates.push({
      category: "Bulletin",
      title: "ICPAC weekly bulletin",
      text: "Drafted from each forecast as a Word document and web page, then released after forecaster review.",
      date: "Weekly",
      href: "/bulletin",
      image: "/images/globe-africa.webp",
      contain: true,
    });
  if (draft)
    updates.push({
      category: "Bulletin",
      title: draft.title,
      text:
        draft.status === "draft"
          ? "Draft ready for forecaster review."
          : draft.status === "under_review"
            ? "Submitted for review."
            : `${draft.status[0].toUpperCase()}${draft.status.slice(1)} by ${draft.reviews.at(-1)?.actor ?? "the reviewer"}.`,
      date: day(draft.created_at),
      href: "/bulletins",
      image: `/api/bulletins/${draft.id}/map`,
      contain: true,
    });
  const verified = runs.data?.find(
    (r) => r.verification_status === "available",
  );
  updates.push(
    verified
      ? {
          category: "Verification",
          title: `Forecast for ${validDays(verified.valid_start, verified.valid_end)} verified`,
          text: "Scored against CHIRPS observations: MAE, RMSE, bias and correlation are available.",
          date: day(verified.generation_time),
          href: "/verification",
          image: "/images/hero-eastern-africa.webp",
        }
      : {
          category: "Verification",
          title: "Verification against CHIRPS",
          text: "Each forecast is scored automatically once CHIRPS covers its week, about two days after it ends.",
          date: "Automatic",
          href: "/verification",
          image: "/images/hero-eastern-africa.webp",
        },
  );
  const ecmwf = sources.data?.find((s) => s.id === "ecmwf")?.latest as
    | { initialization: string; members: number; fetched_at: string }
    | null
    | undefined;
  updates.push({
    category: "Data",
    title: ecmwf
      ? `ECMWF ensemble of ${day(ecmwf.initialization)} downloaded`
      : "ECMWF ensemble input",
    text: ecmwf
      ? `${ecmwf.members} perturbed members of the 00 UTC run, Week-2 rainfall cropped to Eastern Africa.`
      : "The 00 UTC ECMWF ensemble is downloaded from ECMWF Open Data each week.",
    date: ecmwf ? dateTime(ecmwf.fetched_at) : "Weekly",
    href: "/data/ecmwf",
    image: "/images/globe-africa.webp",
    contain: true,
  });
  return (
    <section className="section white" style={{ paddingTop: 24 }}>
      <div className="wrap">
        <h2 className="section-title" style={{ marginBottom: 48 }}>
          Latest Updates
        </h2>
        <div className="grid-4">
          {updates.slice(0, 4).map((update) => (
            <UpdateCard key={update.category} update={update} />
          ))}
        </div>
        <p
          style={{
            textAlign: "center",
            marginTop: 36,
            display: "flex",
            gap: 14,
            justifyContent: "center",
            flexWrap: "wrap",
          }}
        >
          <LinkButton href="/forecasts/archive" variant="outline">
            All forecasts
          </LinkButton>
          <LinkButton href="/bulletins" variant="outline">
            All bulletins
          </LinkButton>
        </p>
      </div>
    </section>
  );
}

function Sources() {
  const sources = useApi<DataSource[]>("/data/sources");
  return (
    <section className="section grey">
      <div className="wrap">
        <h2 className="section-title">Our Data Sources</h2>
        <p className="section-sub">
          Forecasts use the ECMWF ensemble and are verified against CHIRPS.
          TAMSAT, RFE 2.0, ARC 2.0 and IMERG will follow.
        </p>
        <div className="grid-3">
          {(sources.data ?? []).map((source) => (
            <Link
              key={source.id}
              href={`/data/${source.id}`}
              className="card"
              style={{ display: "block", color: "inherit" }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <h3 style={{ fontSize: 21 }}>{source.name}</h3>
                {source.status === "active" ? (
                  <Status tone="ok">In use</Status>
                ) : (
                  <Status tone="planned">Coming later</Status>
                )}
              </div>
              <p
                style={{
                  margin: "10px 0 6px",
                  color: "var(--muted)",
                  fontSize: 14,
                }}
              >
                {source.provider} · {source.role}
              </p>
              <p style={{ margin: 0, fontSize: 15 }}>{source.description}</p>
            </Link>
          ))}
          {sources.loading &&
            [0, 1, 2].map((i) => <Skeleton key={i} height={160} />)}
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const latest = useApi<ForecastDetail>("/forecasts/latest");
  return (
    <>
      <Hero forecast={latest.data} />
      <ForecastSection latest={latest} />
      <Products />
      <Workflow />
      <LatestUpdates detail={latest.data} />
      <Sources />
    </>
  );
}
