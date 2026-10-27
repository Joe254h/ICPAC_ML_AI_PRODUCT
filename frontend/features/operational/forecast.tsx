"use client";
/** The latest (or a chosen) Week-2 forecast: map, outlook text, countries, products. */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, FileDown, FileText, LoaderCircle } from "lucide-react";
import ForecastMap from "@/components/forecast-map";
import { openStaffAccess } from "@/components/bulletin-access";
import ReviewDialog from "@/components/review-dialog";
import { useApp } from "@/components/shell";
import {
  Button,
  Card,
  Disclosure,
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
import { SERIES, num, validDays, weekPeriod } from "@/lib/format";
import { mutate, request } from "@/services/api";
import { useApi } from "@/services/hooks";
import { useStaff } from "@/services/staff";
import type {
  BulletinStatus,
  ForecastDetail,
  InputCheck,
  Variant,
} from "@/types/operational";
import {
  CountryChart,
  CountryTable,
  Downloads,
  EarlierModelNotice,
  ForecastFacts,
  NoForecast,
  ProductStatusList,
  ProvenanceList,
  VerificationSummary,
  forecastFacts,
  laterModel,
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
  const rainfall = sections.find((s) => s.key === "rainfall");
  // The headline repeats one of the rainfall statements: it leads only when it adds one.
  const headline = sections.find(
    (s) => s.key === "headline" && !rainfall?.text.includes(s.text[0]),
  );
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

type Gate = { required?: boolean; review?: unknown } | undefined;

/** A run of a frozen model held for the reviewer's one-time confirmation that the
 * real-time ECMWF input matches the reforecasts it was trained on. */
export function awaitingConfirmation(detail: ForecastDetail): boolean {
  const gate = detail.provenance.realtime_gate as Gate;
  return (
    detail.products?.hybrid?.status === "in_progress" &&
    Boolean(gate?.required) &&
    !gate?.review
  );
}

function RealtimeConfirm({
  detail,
  onIssued,
}: {
  detail: ForecastDetail;
  onIssued: () => void;
}) {
  const { signedIn } = useStaff();
  const [dialog, setDialog] = useState(false);
  const [operation, setOperation] = useState<string | null>(null);
  const [failure, setFailure] = useState("");
  const checks = (detail.provenance.input_checks as InputCheck[]) ?? [];
  const passed = checks.filter((c) => c.status !== "failed").length;
  const clean = checks.length > 0 && passed === checks.length;
  useEffect(() => {
    if (!operation) return;
    const timer = window.setInterval(async () => {
      try {
        const state = await request<{ status: string; error?: string }>(
          `/operations/${operation}`,
        );
        if (state.status === "complete") {
          window.clearInterval(timer);
          onIssued();
        } else if (!["queued", "running"].includes(state.status)) {
          window.clearInterval(timer);
          setOperation(null);
          setFailure(state.error ?? "The forecast run did not finish.");
        }
      } catch {
        // a missed poll is retried on the next tick
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [operation, onIssued]);
  return (
    <section className="card confirm-card" aria-labelledby="confirm-title">
      <div className="confirm-icon" aria-hidden>
        {operation ? (
          <LoaderCircle size={22} className="spin" />
        ) : (
          <CheckCircle2 size={22} />
        )}
      </div>
      <div className="confirm-body">
        <p className="eyebrow">MBC + AI/ML forecast</p>
        <h2 id="confirm-title">
          {operation
            ? "Producing the MBC + AI/ML forecast…"
            : "One confirmation before the first real-time forecast"}
        </h2>
        {operation ? (
          <p>
            The confirmation is recorded. The forecast is being run again with
            the AI/ML correction; this page shows it when it is ready (about a
            minute).
          </p>
        ) : (
          <p>
            The AI/ML model was trained and tested on ECMWF reforecasts. A
            reviewer confirms once that the real-time ECMWF input matches them.{" "}
            {clean
              ? `This run passed all ${checks.length} automated input checks: members, the Days 8–14 accumulation, units, grid, the seven upper-air forecast hours, the 30 atmospheric predictors, PCA and MBC.`
              : `${passed} of ${checks.length} automated input checks passed; the input cannot be confirmed until all of them pass.`}{" "}
            Until then this forecast is issued from MBC.
          </p>
        )}
        {failure && <Notice tone="red">{failure}</Notice>}
        {!operation && (
          <div className="confirm-actions">
            {signedIn ? (
              <Button disabled={!clean} onClick={() => setDialog(true)}>
                Review and confirm
              </Button>
            ) : (
              <Button onClick={openStaffAccess}>Sign in to confirm</Button>
            )}
            <Link href="/data/ecmwf">See every input check</Link>
          </div>
        )}
      </div>
      {dialog && (
        <ReviewDialog
          title="Confirm the real-time ECMWF input"
          description={`The ${detail.model?.model_name ?? "frozen"} model was trained and tested on ECMWF reforecasts. Confirming records that the real-time ECMWF Open Data input matches them, with this run's ${checks.length} passed input checks as the evidence, and runs the forecast again with the AI/ML correction. The 2022–2024 test scores still describe reforecasts, not real-time skill.`}
          statement="I reviewed the input checks and the source's model cycle, members, accumulation, units and grid, and confirm the input is compatible."
          confirmLabel="Confirm and run"
          onClose={() => setDialog(false)}
          onSubmit={async (review) => {
            setFailure("");
            await mutate(`/models/${detail.model_id}/realtime-review`, {
              ...review,
              source: "ecmwf_opendata",
              forecast_id: detail.forecast_id,
              withdraw: false,
            });
            const run = await mutate<{ id: string }>("/operations", {
              action: "run_forecast",
              initialization: detail.initialization.slice(0, 10),
              actor: review.actor,
            });
            setOperation(run.id);
          }}
        />
      )}
    </section>
  );
}

function Body({
  detail,
  onIssued,
}: {
  detail: ForecastDetail;
  onIssued: () => void;
}) {
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
  const { current } = useApp();
  // A forecast from the earlier model: what it was waiting for no longer applies.
  const earlier = laterModel(detail, current.data) !== null;
  return (
    <>
      <PageBanner
        title={`Weekly Forecast for ${weekPeriod(detail.valid_start, detail.valid_end)}`}
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
                variant="outline"
              >
                <FileDown size={18} /> Word draft
              </LinkButton>
            )}
          </>
        }
      />
      {earlier ? (
        <EarlierModelNotice detail={detail} />
      ) : awaitingConfirmation(detail) ? (
        <RealtimeConfirm detail={detail} onIssued={onIssued} />
      ) : (
        hybrid?.status === "in_progress" && (
          <Notice title="Issued from MBC.">
            The MBC + AI/ML layer is waiting for {hybrid.reason}. This forecast
            gives the raw ECMWF and MBC-corrected rainfall.
          </Notice>
        )
      )}
      {!earlier && hybrid?.status === "blocked" && (
        <Notice tone="red" title="Issued from MBC.">
          The MBC + AI/ML hybrid was not produced: {hybrid.reason}. Nothing was
          filled in; this forecast provides raw ECMWF and the MBC-corrected
          rainfall. See the <Link href="/data/ecmwf">ECMWF input checks</Link>.
        </Notice>
      )}
      {!earlier && hybrid?.status === "not_produced" && (
        <Notice title="Issued from MBC.">{hybrid.reason}.</Notice>
      )}
      <div className="stats">
        <Stat
          label={`Regional mean · ${SERIES[primary].label}`}
          value={num(means[primary])}
          unit="mm"
          hint="Area average over the eleven member states"
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
        title="Country outlook"
        subtitle="Area means and ranges of Week-2 rainfall (mm) per member state."
      >
        <CountryTable rows={detail.countries} layers={layers} />
        <div style={{ marginTop: 28 }}>
          <CountryChart rows={detail.countries} layers={layers} />
        </div>
      </Card>
      <Card
        title="Forecast products"
        subtitle="Each layer and what it is made from."
      >
        <ProductStatusList detail={detail} />
      </Card>
      <div className="grid-2">
        <Card title="Verification">
          <VerificationSummary detail={detail} />
        </Card>
        <Card title="Downloads" subtitle="This forecast's data and maps.">
          <Downloads detail={detail} />
        </Card>
      </div>
      <Disclosure
        title="How this forecast was made"
        subtitle="The run, the inputs, the grid and the correction."
      >
        <div>
          <h3>Forecast details</h3>
          <ForecastFacts detail={detail} />
        </div>
        {!!detail.notes?.length && (
          <div>
            <h3>Notes on this forecast</h3>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {detail.notes.map((note) => (
                <li key={note} style={{ marginBottom: 6 }}>
                  {note}
                </li>
              ))}
            </ul>
          </div>
        )}
        <div>
          <h3>Method</h3>
          <ProvenanceList detail={detail} />
        </div>
      </Disclosure>
    </>
  );
}

export default function Forecast({ id }: PageProps) {
  const forecast = useForecast(id);
  const router = useRouter();
  const { reload } = forecast;
  // A re-run issues a new forecast: the latest one is then that one.
  const issued = useCallback(
    () => (id ? router.push("/forecasts") : reload()),
    [id, router, reload],
  );
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
        {forecast.data && (
          <Body
            key={forecast.data.forecast_id}
            detail={forecast.data}
            onIssued={issued}
          />
        )}
      </div>
    </div>
  );
}
