"use client";
/** Weekly bulletin drafts and their review: draft → review → approval → publication. */
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { FileDown, FilePlus2, Globe2, Mail, RefreshCw } from "lucide-react";
import ReviewDialog from "@/components/review-dialog";
import type { Review } from "@/components/review-dialog";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  KeyValues,
  LinkButton,
  Notice,
  PageBanner,
  Skeleton,
  Status,
} from "@/components/ui";
import type { Tone } from "@/components/ui";
import type { PageProps } from "@/features/view";
import { useActor } from "@/lib/actor";
import { dateTime, day, personName, weekPeriod } from "@/lib/format";
import { mutate, request } from "@/services/api";
import { useApi } from "@/services/hooks";
import type { ForecastRun } from "@/types/operational";
import type { Bulletin, EmailNotice, EmailStatus } from "@/types/workflows";

/** A forecast as people know it: its week and the ECMWF run it came from. */
function forecastLabel(run: ForecastRun): string {
  return `${weekPeriod(run.valid_start, run.valid_end)} · run of ${day(run.initialization)}`;
}

/** Drafts grouped by their forecast, newest forecast week first; drafts of a forecast no
 * longer listed come last. */
function byForecast(drafts: Bulletin[], runs: ForecastRun[]) {
  const order = new Map(runs.map((run, i) => [run.forecast_id, i]));
  const groups = new Map<string, Bulletin[]>();
  for (const draft of drafts) {
    const key = draft.forecast_id ?? draft.facts.forecast_id;
    groups.set(key, [...(groups.get(key) ?? []), draft]);
  }
  return [...groups.entries()]
    .map(([forecastId, items]) => ({
      forecastId,
      run: runs.find((r) => r.forecast_id === forecastId),
      items,
    }))
    .sort(
      (a, b) =>
        (order.get(a.forecastId) ?? Number.MAX_SAFE_INTEGER) -
        (order.get(b.forecastId) ?? Number.MAX_SAFE_INTEGER),
    );
}

const STATUS: Record<Bulletin["status"], [string, Tone]> = {
  draft: ["Draft", "info"],
  under_review: ["Under review", "progress"],
  approved: ["Approved", "ok"],
  published: ["Published", "ok"],
  rejected: ["Rejected", "bad"],
};

const STEPS = ["draft", "under_review", "approved", "published"] as const;

const DECIDED: Record<string, string> = {
  submit: "Submitted",
  approve: "Approved",
  reject: "Rejected",
  publish: "Published",
};

const HEADER: Record<string, string> = {
  approved: "APPROVED",
  published: "PUBLISHED",
  rejected: "REJECTED - NOT FOR RELEASE",
};

/** The Word document's page header: the draft label until a decision names the
 * reviewer and date (as the backend stamps it). */
function documentHeader(draft: Bulletin): string {
  const state = HEADER[draft.status];
  const review = [...draft.reviews]
    .reverse()
    .find((r) => r.to === draft.status);
  if (!state || !review) return draft.facts.label;
  const scope = draft.facts.label
    .split(" · ")
    .filter(
      (part) =>
        part !== "DRAFT - NOT APPROVED" &&
        part !== "forecaster review required",
    );
  return [
    `${state} by ${personName(review.actor)} on ${day(review.timestamp)}`,
    ...scope,
  ].join(" · ");
}

const ACTIONS: Record<
  string,
  {
    action: string;
    label: string;
    description: string;
    variant: "green" | "amber" | "outline";
  }[]
> = {
  draft: [
    {
      action: "submit",
      label: "Submit for review",
      description:
        "Send this draft to a reviewer. Its words, maps and Word document stay frozen.",
      variant: "green",
    },
  ],
  under_review: [
    {
      action: "approve",
      label: "Approve",
      description:
        "Approve the bulletin for release. The approved text and maps are sealed so they cannot change.",
      variant: "green",
    },
    {
      action: "reject",
      label: "Reject",
      description:
        "Reject this draft. A revised draft can be made from the same forecast.",
      variant: "outline",
    },
  ],
  approved: [
    {
      action: "publish",
      label: "Publish",
      description:
        "Mark the approved bulletin as published. ICPAC disseminates it through its own channels.",
      variant: "amber",
    },
  ],
};

function Stepper({ status }: { status: Bulletin["status"] }) {
  const index =
    status === "rejected" ? 1 : STEPS.indexOf(status as (typeof STEPS)[number]);
  return (
    <ol className="stepper" aria-label="Review progress">
      {STEPS.map((step, i) => (
        <li
          key={step}
          className={
            i < index || status === "published"
              ? "done"
              : i === index
                ? "now"
                : ""
          }
        >
          <span className="n">{i + 1}</span>
          {STATUS[step][0]}
        </li>
      ))}
      {status === "rejected" && (
        <li className="now">
          <span className="n" style={{ background: "var(--red)" }}>
            ×
          </span>
          Rejected
        </li>
      )}
    </ol>
  );
}

const WHO: Record<string, string> = {
  review: "reviewers",
  publish: "publishers",
  published: "distribution list",
  rejected: "reviewers",
};

/** Who is emailed at this step, and what was last sent. */
function EmailLine({
  draft,
  status,
  onResend,
}: {
  draft: Bulletin;
  status?: EmailStatus;
  onResend: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  if (!status) return null;
  if (!status.configured)
    return (
      <p className="email-line">
        <Mail size={16} aria-hidden /> Email is not set up, so every step is
        taken on this page.
      </p>
    );
  const last: EmailNotice | undefined = draft.emails?.at(-1);
  let text: string;
  if (draft.status === "draft")
    text = status.reviewers
      ? `Submitting emails ${status.reviewers} reviewer${status.reviewers === 1 ? "" : "s"} a link to approve or reject.`
      : "No reviewers' addresses are set up; review on this page.";
  else if (last?.sent?.length)
    text = `Emailed to the ${WHO[last.step ?? ""] ?? "recipients"} (${last.sent.join(", ")}) on ${dateTime(last.at)}.`;
  else if (last?.skipped) text = last.skipped;
  else text = "No email has been sent for this step.";
  const resendable =
    draft.status === "under_review" || draft.status === "approved";
  return (
    <p className="email-line">
      <Mail size={16} aria-hidden /> {text}
      {!!last?.failed?.length &&
        ` Could not reach ${last.failed.map((f) => f.to).join(", ")}.`}
      {resendable && (
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onResend();
            } finally {
              setBusy(false);
            }
          }}
        >
          Send again
        </Button>
      )}
    </p>
  );
}

function Detail({
  draft,
  onChanged,
  onRevise,
  busy,
}: {
  draft: Bulletin;
  onChanged: (draft: Bulletin) => void;
  onRevise: () => void;
  busy: boolean;
}) {
  const [dialog, setDialog] = useState<(typeof ACTIONS)[string][number] | null>(
    null,
  );
  const [label, tone] = STATUS[draft.status];
  const close = useCallback(() => setDialog(null), []);
  const email = useApi<EmailStatus>("/bulletins/email-status");
  const [actor] = useActor();
  const resend = async () => {
    await mutate(`/bulletins/${draft.id}/resend`, {
      actor: actor || "Forecaster",
    });
    onChanged(await request<Bulletin>(`/bulletins/${draft.id}`));
  };
  const submit = async (review: Review) => {
    if (!dialog) return;
    onChanged(
      await mutate<Bulletin>(`/bulletins/${draft.id}/${dialog.action}`, review),
    );
  };
  return (
    <>
      <Card
        eyebrow="Weekly bulletin draft"
        title={draft.title}
        action={<Status tone={tone}>{label}</Status>}
      >
        <Stepper status={draft.status} />
        <EmailLine draft={draft} status={email.data} onResend={resend} />
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 12,
            margin: "22px 0",
          }}
        >
          {(ACTIONS[draft.status] ?? []).map((action) => (
            <Button
              key={action.action}
              variant={action.variant}
              onClick={() => setDialog(action)}
            >
              {action.label}
            </Button>
          ))}
          {draft.status !== "published" && (
            <Button variant="outline" onClick={onRevise} disabled={busy}>
              <RefreshCw size={16} /> New revision
            </Button>
          )}
          <LinkButton
            href={`/api/bulletins/${draft.id}/export?format=docx`}
            variant="outline"
          >
            <FileDown size={16} /> Word
          </LinkButton>
          <LinkButton
            href={`/api/bulletins/${draft.id}/export?inline=true`}
            variant="outline"
          >
            <Globe2 size={16} /> Web page
          </LinkButton>
        </div>
        {draft.consistency.status !== "PASS" && (
          <Notice tone="red" title="Consistency check failed.">
            The text no longer matches the sections frozen with this draft; make
            a new revision before reviewing it.
          </Notice>
        )}
        <KeyValues
          items={[
            [
              "Created",
              `${dateTime(draft.created_at)}${draft.created_by ? ` by ${personName(draft.created_by)}` : ""}`,
            ],
            [
              "Consistency",
              draft.consistency.status === "PASS"
                ? "Passed: text matches the frozen sections"
                : "Failed",
            ],
            ["Document header", documentHeader(draft)],
            [
              "Revision",
              draft.parent_id
                ? `Version ${draft.version ?? 2}, a revision of an earlier draft`
                : "First draft",
            ],
            ...(draft.edited
              ? ([
                  [
                    "Changed with the Copilot",
                    `${draft.edited.summary ?? "Wording changed"} (asked by ${personName(draft.edited.by)}; ${
                      draft.edited.changed?.join(", ") ?? ""
                    })`,
                  ],
                ] as [string, string][])
              : []),
          ]}
        />
        {draft.reviews.length > 0 && (
          <div className="table-wrap" style={{ marginTop: 20 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>When (EAT)</th>
                  <th>Decision</th>
                  <th>Reviewer</th>
                  <th>Justification</th>
                </tr>
              </thead>
              <tbody>
                {draft.reviews.map((review, i) => (
                  <tr key={i}>
                    <td>{dateTime(review.timestamp)}</td>
                    <td className="strong">
                      {DECIDED[review.action] ?? review.action}
                    </td>
                    <td>{personName(review.actor)}</td>
                    <td>{review.comment}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card
        title="Preview"
        subtitle="The bulletin's web page, as exported. The Word document carries the same words and maps."
      >
        <iframe
          className="preview-frame"
          title={`Preview of ${draft.title}`}
          src={`/api/bulletins/${draft.id}/export?inline=true`}
        />
      </Card>
      {dialog && (
        <ReviewDialog
          title={`${dialog.label}: ${draft.title}`}
          description={dialog.description}
          confirmLabel={dialog.label}
          onClose={close}
          onSubmit={submit}
        />
      )}
    </>
  );
}

export default function Bulletins({ id }: PageProps) {
  const drafts = useApi<Bulletin[]>("/bulletins");
  const forecasts = useApi<ForecastRun[]>("/forecasts");
  const router = useRouter();
  const [actor] = useActor();
  const [selected, setSelected] = useState<string | undefined>(id);
  const [chosen, setChosen] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState<string | null>(null);
  useEffect(() => setSelected(id), [id]);
  const runs = (forecasts.data ?? []).filter((r) => !r.synthetic);
  const newest = runs[0];
  const target = chosen || newest?.forecast_id || "";
  const groups = byForecast(drafts.data ?? [], runs);
  const active =
    drafts.data?.find((d) => d.id === selected) ?? groups[0]?.items[0];
  const newestDrafted =
    !newest ||
    (drafts.data ?? []).some((d) => d.forecast_id === newest.forecast_id);

  const create = async (parent?: Bulletin, forecastId?: string) => {
    setBusy(true);
    setError(null);
    setOpened(null);
    try {
      const draft = await mutate<Bulletin & { reused?: boolean }>(
        "/bulletins/generate" + (parent ? `?parent_id=${parent.id}` : ""),
        {
          actor: actor || "Forecaster",
          ...(parent || !forecastId ? {} : { forecast_id: forecastId }),
        },
      );
      if (draft.reused)
        setOpened(
          "This forecast already has a draft waiting for review, so it is opened instead of making a second one.",
        );
      drafts.reload();
      router.replace(`/bulletins?id=${draft.id}`);
      setSelected(draft.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const picker = runs.length > 0 && (
    <div className="draft-picker">
      <label className="field">
        Forecast to draft
        <select
          value={target}
          onChange={(e) => setChosen(e.target.value)}
          aria-label="Forecast to draft"
        >
          {runs.map((run, i) => (
            <option key={run.forecast_id} value={run.forecast_id}>
              {forecastLabel(run)}
              {i === 0 ? " (newest)" : ""}
            </option>
          ))}
        </select>
      </label>
      <Button
        variant="amber"
        onClick={() => create(undefined, target)}
        disabled={busy || !target}
      >
        <FilePlus2 size={18} /> {busy ? "Preparing…" : "Draft this week"}
      </Button>
    </div>
  );

  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Bulletin Drafts and Review"
          crumbs={[
            { label: "Bulletin", href: "/bulletin" },
            { label: "Drafts and review" },
          ]}
          subtitle="Every weekly bulletin goes from draft to review, approval and publication. Each decision needs a named reviewer and a justification, and approved content is sealed so it cannot change."
        />
        <Card
          title="Draft a weekly bulletin"
          subtitle={
            newest
              ? `The newest forecast is for ${weekPeriod(newest.valid_start, newest.valid_end)}, from the ECMWF run of ${day(newest.initialization)}. Drafts below are grouped by forecast week, newest first.`
              : "A draft is made from a forecast; none has been issued yet."
          }
        >
          {forecasts.loading && !forecasts.data && <Skeleton height={60} />}
          {picker}
          {newest && !newestDrafted && (
            <Notice tone="amber">
              The newest forecast has no bulletin draft yet.
            </Notice>
          )}
          {opened && <Notice>{opened}</Notice>}
        </Card>
        {error && <ErrorState message={error} />}
        {drafts.loading && <Skeleton height={420} />}
        {drafts.error && (
          <ErrorState message={drafts.error} retry={drafts.reload} />
        )}
        {drafts.data && !drafts.data.length && (
          <EmptyState
            title="No bulletin draft yet"
            action={
              <Button
                variant="amber"
                onClick={() => create(undefined, target)}
                disabled={busy || !target}
              >
                Create the first draft
              </Button>
            }
          >
            <p style={{ margin: 0 }}>
              A draft is made from the latest forecast: the ICPAC weekly
              bulletin&apos;s sections, its Word document and its maps.
            </p>
          </EmptyState>
        )}
        {drafts.data && drafts.data.length > 0 && active && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 300px) minmax(0, 1fr)",
              gap: 28,
            }}
            className="drafts-layout"
          >
            <aside className="draft-list" aria-label="Drafts">
              {groups.map((group) => (
                <section key={group.forecastId} className="draft-group">
                  <h3>
                    {group.run
                      ? weekPeriod(group.run.valid_start, group.run.valid_end)
                      : group.items[0].facts.period}
                    <small>
                      {group.run
                        ? `Run of ${day(group.run.initialization)}${
                            group.run.forecast_id === newest?.forecast_id
                              ? " · newest forecast"
                              : ""
                          }`
                        : "Forecast no longer listed"}
                    </small>
                  </h3>
                  {group.items.map((draft) => (
                    <button
                      key={draft.id}
                      type="button"
                      aria-current={draft.id === active.id}
                      onClick={() => {
                        setSelected(draft.id);
                        router.replace(`/bulletins?id=${draft.id}`);
                      }}
                    >
                      <strong>
                        {draft.version && draft.version > 1
                          ? `Version ${draft.version}`
                          : "First draft"}
                      </strong>
                      <span>
                        <Status tone={STATUS[draft.status][1]}>
                          {STATUS[draft.status][0]}
                        </Status>
                      </span>
                      <small>Created {dateTime(draft.created_at)}</small>
                    </button>
                  ))}
                </section>
              ))}
            </aside>
            <div style={{ display: "grid", gap: 28, minWidth: 0 }}>
              <Detail
                key={active.id}
                draft={active}
                busy={busy}
                onRevise={() => create(active)}
                onChanged={() => drafts.reload()}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
