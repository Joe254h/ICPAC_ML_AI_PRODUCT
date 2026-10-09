"use client";
/** Weekly bulletin drafts and their review: draft → review → approval → publication. */
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { FileDown, FilePlus2, Globe2, RefreshCw } from "lucide-react";
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
import { dateTime, day } from "@/lib/format";
import { mutate } from "@/services/api";
import { useApi } from "@/services/hooks";
import type { Bulletin } from "@/types/workflows";

const STATUS: Record<Bulletin["status"], [string, Tone]> = {
  draft: ["Draft", "info"],
  under_review: ["Under review", "progress"],
  approved: ["Approved", "ok"],
  published: ["Published", "ok"],
  rejected: ["Rejected", "bad"],
};

const STEPS = ["draft", "under_review", "approved", "published"] as const;

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
        "Approve the bulletin for release. The approved content is sealed with checksums.",
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
  const submit = async (review: Review) => {
    if (!dialog) return;
    onChanged(
      await mutate<Bulletin>(`/bulletins/${draft.id}/${dialog.action}`, review),
    );
  };
  return (
    <>
      <Card
        eyebrow={`Forecast ${draft.forecast_id ?? ""}`}
        title={draft.title}
        action={<Status tone={tone}>{label}</Status>}
      >
        <Stepper status={draft.status} />
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
          <Notice tone="red" title="Consistency check failed:">
            {draft.consistency.errors.join("; ")}
          </Notice>
        )}
        <KeyValues
          items={[
            [
              "Created",
              `${dateTime(draft.created_at)}${draft.created_by ? ` by ${draft.created_by}` : ""}`,
            ],
            [
              "Consistency",
              draft.consistency.status === "PASS"
                ? "Passed: text matches the frozen sections"
                : "Failed",
            ],
            ["Label", draft.facts.label],
            ["Revision of", draft.parent_id ?? "—"],
          ]}
        />
        {draft.reviews.length > 0 && (
          <div className="table-wrap" style={{ marginTop: 20 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>When (UTC)</th>
                  <th>Decision</th>
                  <th>Reviewer</th>
                  <th>Justification</th>
                </tr>
              </thead>
              <tbody>
                {draft.reviews.map((review, i) => (
                  <tr key={i}>
                    <td>{dateTime(review.timestamp)}</td>
                    <td className="strong">{review.action}</td>
                    <td>{review.actor}</td>
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
  const router = useRouter();
  const [actor] = useActor();
  const [selected, setSelected] = useState<string | undefined>(id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setSelected(id), [id]);
  const active =
    drafts.data?.find((d) => d.id === selected) ?? drafts.data?.[0];

  const create = async (parent?: Bulletin) => {
    setBusy(true);
    setError(null);
    try {
      const draft = await mutate<Bulletin>(
        "/bulletins/generate" + (parent ? `?parent_id=${parent.id}` : ""),
        { actor: actor || "Forecaster" },
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

  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Bulletin Drafts and Review"
          crumbs={[
            { label: "Bulletin", href: "/bulletin" },
            { label: "Drafts and review" },
          ]}
          subtitle="Every weekly bulletin goes from draft to review, approval and publication. Each decision needs a named reviewer and a justification, and approved content is sealed with checksums."
          actions={
            <Button variant="amber" onClick={() => create()} disabled={busy}>
              <FilePlus2 size={18} />{" "}
              {busy ? "Preparing…" : "New draft from the latest forecast"}
            </Button>
          }
        />
        {error && <ErrorState message={error} />}
        {drafts.loading && <Skeleton height={420} />}
        {drafts.error && (
          <ErrorState message={drafts.error} retry={drafts.reload} />
        )}
        {drafts.data && !drafts.data.length && (
          <EmptyState
            title="No bulletin draft yet"
            action={
              <Button variant="amber" onClick={() => create()} disabled={busy}>
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
              {drafts.data.map((draft) => (
                <button
                  key={draft.id}
                  type="button"
                  aria-current={draft.id === active.id}
                  onClick={() => {
                    setSelected(draft.id);
                    router.replace(`/bulletins?id=${draft.id}`);
                  }}
                >
                  <strong>{draft.title}</strong>
                  <span>
                    <Status tone={STATUS[draft.status][1]}>
                      {STATUS[draft.status][0]}
                    </Status>
                  </span>
                  <small>Created {day(draft.created_at)}</small>
                </button>
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
