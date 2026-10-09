"use client";
/** The latest (or a chosen) Week-2 forecast: map, outlook text, countries, products. */
import { useState } from "react";
import { FileDown, FileText } from "lucide-react";
import ForecastMap from "@/components/forecast-map";
import {
  Card,
  ErrorState,
  LinkButton,
  MapFigure,
  Notice,
  PageBanner,
  Skeleton,
  Stat,
  Tabs,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import { SERIES, num, validDays } from "@/lib/format";
import { useApi } from "@/services/hooks";
import type {
  BulletinStatus,
  ForecastDetail,
  Variant,
} from "@/types/operational";
import {
  CountryChart,
  CountryTable,
  Downloads,
  ForecastFacts,
  NoForecast,
  NotesCard,
  ProductStatusList,
  ProvenanceList,
  VerificationSummary,
  forecastFacts,
  layersOf,
  mapUrl,
  methodName,
  primaryOf,
  useForecast,
} from "@/features/operational/shared";

function rich(text: string, lead?: string) {
  if (lead && text.startsWith(lead))
    return (
      <>
        <strong>{lead}</strong>
        {text.slice(lead.length)}
      </>
    );
  return text;
}

function Outlook({ bulletin }: { bulletin?: BulletinStatus }) {
  const sections = bulletin?.sections ?? [];
  const headline = sections.find((s) => s.key === "headline");
  const rainfall = sections.find((s) => s.key === "rainfall");
  if (!headline && !rainfall) return <Skeleton height={180} />;
  return (
    <>
      {headline && (
        <p style={{ fontSize: 19, marginTop: 0 }}>
          {rich(headline.text[0], headline.leads?.[0])}
        </p>
      )}
      {rainfall && (
        <ul style={{ paddingLeft: 20, margin: 0 }}>
          {rainfall.text.map((text, i) => (
            <li key={i} style={{ marginBottom: 10 }}>
              {rich(text, rainfall.leads?.[i])}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Body({ detail }: { detail: ForecastDetail }) {
  const layers = layersOf(detail);
  const primary = primaryOf(detail);
  const [mapLayer, setMapLayer] = useState<Variant>(primary);
  const [figureLayer, setFigureLayer] = useState<Variant>(primary);
  const bulletin = useApi<BulletinStatus>(
    `/forecasts/${detail.forecast_id}/bulletin`,
  );
  const means = detail.interpretation.domain_mean_mm;
  const wettest = [...detail.countries].sort(
    (a, b) => (b[primary]?.mean_mm ?? 0) - (a[primary]?.mean_mm ?? 0),
  )[0];
  const hybrid = detail.products?.hybrid;
  return (
    <>
      <PageBanner
        title={bulletin.data?.title ?? "Latest Week-2 Forecast"}
        crumbs={[
          { label: "Forecasts", href: "/forecasts/archive" },
          { label: "Latest forecast" },
        ]}
        subtitle={`Week-2 (days 8–14) total rainfall over the eleven ICPAC member states, valid ${validDays(detail.valid_start, detail.valid_end)}.`}
        facts={forecastFacts(detail)}
        actions={
          <>
            <LinkButton
              href={`/bulletin?id=${detail.forecast_id}`}
              variant="amber"
            >
              <FileText size={18} /> Weekly bulletin
            </LinkButton>
            {bulletin.data?.export && (
              <LinkButton
                href={"/api" + bulletin.data.export}
                variant="ghost-light"
              >
                <FileDown size={18} /> Word draft
              </LinkButton>
            )}
          </>
        }
      />
      {hybrid?.status === "in_progress" && (
        <Notice title="Issued from MBC.">
          The MBC + AI/ML hybrid is still in progress: it needs {hybrid.reason}.
          This forecast provides raw ECMWF and the MBC-corrected rainfall.
        </Notice>
      )}
      <div className="stats">
        <Stat
          label={`Regional mean · ${SERIES[primary].label}`}
          value={num(means[primary])}
          unit="mm"
          hint="Area mean over the 205,999-cell domain"
        />
        <Stat
          label="Regional mean · raw ECMWF"
          value={num(means.raw)}
          unit="mm"
          hint="Before correction"
        />
        <Stat
          label="Wettest country"
          value={wettest?.country ?? "—"}
          hint={
            wettest
              ? `${num(wettest[primary]?.mean_mm)} mm area mean`
              : undefined
          }
          tone="amber"
        />
        <Stat
          label="Ensemble"
          value={detail.provenance.ensemble_members}
          unit="members"
          hint={methodName(detail)}
        />
      </div>
      <Card
        title="Rainfall outlook"
        subtitle="Hover over a country for its mean; switch layers on the left."
      >
        <ForecastMap
          detail={detail}
          layer={mapLayer}
          onLayer={setMapLayer}
          height={600}
        />
      </Card>
      <div className="grid-2">
        <Card eyebrow="Weekly bulletin" title="What the forecast says">
          <Outlook bulletin={bulletin.data} />
        </Card>
        <Card
          eyebrow="Bulletin map"
          title="Total rainfall"
          action={
            <Tabs
              label="Map layer"
              value={figureLayer}
              onChange={setFigureLayer}
              options={layers.map((layer) => ({
                value: layer,
                label: SERIES[layer].label,
              }))}
            />
          }
        >
          <MapFigure
            src={mapUrl(detail, figureLayer)}
            alt={`${SERIES[figureLayer].label} Week-2 rainfall map`}
            caption={`${SERIES[figureLayer].label} · valid ${validDays(detail.valid_start, detail.valid_end)}`}
          />
        </Card>
      </div>
      <Card
        title="Forecast products"
        subtitle="Each layer and what it is made from."
      >
        <ProductStatusList detail={detail} />
      </Card>
      <Card
        title="Country outlook"
        subtitle="Area means and ranges of Week-2 rainfall (mm) per member state."
      >
        <CountryTable rows={detail.countries} layers={layers} />
        <div style={{ marginTop: 28 }}>
          <CountryChart rows={detail.countries} layers={layers} />
        </div>
      </Card>
      <Card title="Verification">
        <VerificationSummary detail={detail} />
      </Card>
      <div className="grid-2">
        <Card title="Forecast details">
          <ForecastFacts detail={detail} />
        </Card>
        <Card
          title="Downloads"
          subtitle="The forecast's product package, with checksums."
        >
          <Downloads detail={detail} />
        </Card>
      </div>
      <NotesCard detail={detail} />
      <Card title="Provenance">
        <ProvenanceList detail={detail} />
      </Card>
    </>
  );
}

export default function Forecast({ id }: PageProps) {
  const forecast = useForecast(id);
  return (
    <div className="page">
      <div className="wrap">
        {forecast.loading && <Skeleton height={520} />}
        {forecast.status === 404 && (
          <>
            <PageBanner
              title="Latest Week-2 Forecast"
              crumbs={[{ label: "Forecasts" }]}
            />
            <NoForecast />
          </>
        )}
        {forecast.error && forecast.status !== 404 && (
          <ErrorState message={forecast.error} retry={forecast.reload} />
        )}
        {forecast.data && <Body detail={forecast.data} />}
      </div>
    </div>
  );
}
