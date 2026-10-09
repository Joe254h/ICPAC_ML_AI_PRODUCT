"use client";
/** The weekly bulletin of the latest (or a chosen) forecast, as forecasters will issue it. */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { FileDown, FilePlus2 } from "lucide-react";
import {
  Button,
  Card,
  ErrorState,
  InProgress,
  LinkButton,
  MapFigure,
  Notice,
  PageBanner,
  Skeleton,
} from "@/components/ui";
import type { PageProps } from "@/features/view";
import { useActor } from "@/lib/actor";
import { validDays } from "@/lib/format";
import { mutate } from "@/services/api";
import { useApi } from "@/services/hooks";
import type { BulletinStatus, ForecastDetail } from "@/types/operational";
import type { Bulletin as Draft } from "@/types/workflows";
import {
  NoForecast,
  forecastFacts,
  useForecast,
} from "@/features/operational/shared";

type Section = NonNullable<BulletinStatus["sections"]>[number];

function Rich({ text, lead }: { text: string; lead?: string }) {
  if (lead && text.startsWith(lead))
    return (
      <>
        <strong>{lead}</strong>
        {text.slice(lead.length)}
      </>
    );
  return <>{text}</>;
}

function Bullets({ section }: { section: Section }) {
  return (
    <ul style={{ margin: 0, paddingLeft: 20 }}>
      {section.text.map((text, i) => (
        <li key={i} style={{ marginBottom: 10 }}>
          <Rich text={text} lead={section.leads?.[i]} />
        </li>
      ))}
    </ul>
  );
}

function Product({ section, eyebrow }: { section: Section; eyebrow: string }) {
  return (
    <Card>
      <div className="split" style={{ alignItems: "start", gap: 32 }}>
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2 style={{ fontSize: 26, marginBottom: 16 }}>{section.title}</h2>
          <Bullets section={section} />
        </div>
        {section.map && (
          <MapFigure src={"/api" + section.map} alt={section.title + " map"} />
        )}
      </div>
    </Card>
  );
}

function Body({ detail }: { detail: ForecastDetail }) {
  const status = useApi<BulletinStatus>(
    `/forecasts/${detail.forecast_id}/bulletin`,
  );
  const router = useRouter();
  const [actor] = useActor();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sections = status.data?.sections ?? [];
  const get = (key: string) => sections.find((s) => s.key === key);
  const headline = get("headline");
  const note = get("decision_support");
  const pending = sections.filter((s) => s.missing_dependency);
  const draft = async () => {
    setBusy(true);
    setError(null);
    try {
      const record = await mutate<Draft>("/bulletins/generate", {
        forecast_id: detail.forecast_id,
        actor: actor || "Forecaster",
      });
      router.push(`/bulletins?id=${record.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <>
      <PageBanner
        title={status.data?.title ?? "Weekly Forecast"}
        crumbs={[{ label: "Bulletin" }, { label: "Weekly bulletin" }]}
        subtitle={`The ICPAC weekly bulletin for ${validDays(detail.valid_start, detail.valid_end)}, written from the forecast with the template's wording. It is released after forecaster review.`}
        facts={forecastFacts(detail)}
        actions={
          <>
            <Button variant="amber" onClick={draft} disabled={busy}>
              <FilePlus2 size={18} />{" "}
              {busy ? "Preparing draft…" : "Create draft for review"}
            </Button>
            {status.data?.export && (
              <LinkButton
                href={"/api" + status.data.export}
                variant="ghost-light"
              >
                <FileDown size={18} /> Word document
              </LinkButton>
            )}
          </>
        }
      />
      {error && <ErrorState message={error} />}
      {status.loading && <Skeleton height={480} />}
      {status.error && (
        <ErrorState message={status.error} retry={status.reload} />
      )}
      {headline && (
        <Card eyebrow="This week" title="Headline" className="headline-card">
          {headline.text.map((text, i) => (
            <p key={i} style={{ fontSize: 18, margin: "0 0 8px" }}>
              <Rich text={text} lead={headline.leads?.[i]} />
            </p>
          ))}
        </Card>
      )}
      {note && (
        <div className="notice green" style={{ display: "block" }}>
          <Rich text={note.text[0]} lead={note.leads?.[0]} />
        </div>
      )}
      {get("rainfall") && (
        <Product
          section={get("rainfall") as Section}
          eyebrow="Regional outlook"
        />
      )}
      {get("somalia") && !get("somalia")?.missing_dependency && (
        <Product section={get("somalia") as Section} eyebrow="Country focus" />
      )}
      {pending.length > 0 && (
        <Card
          eyebrow="Coming soon"
          title="Products in progress"
          subtitle="These sections keep their place in the bulletin and say what they need; nothing is inferred for them."
        >
          <div className="grid-3">
            {pending.map((section) => (
              <InProgress key={section.key} title={section.title}>
                Requires {section.missing_dependency}.
              </InProgress>
            ))}
          </div>
        </Card>
      )}
      {status.data?.generator.status !== "ready" && status.data && (
        <Notice title="Word document unavailable.">
          {status.data.generator.missing_dependency}
        </Notice>
      )}
    </>
  );
}

export default function Bulletin({ id }: PageProps) {
  const forecast = useForecast(id);
  return (
    <div className="page">
      <div className="wrap">
        {forecast.loading && <Skeleton height={520} />}
        {forecast.status === 404 && (
          <>
            <PageBanner
              title="Weekly Bulletin"
              crumbs={[{ label: "Bulletin" }]}
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
