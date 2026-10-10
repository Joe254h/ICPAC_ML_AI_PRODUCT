"use client";
/**
 * The page an emailed link opens: the bulletin and the decision the link allows (approve
 * or reject, or publish). Nothing changes until the person confirms here.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { FileDown, Globe2 } from "lucide-react";
import {
  Button,
  Card,
  ErrorState,
  LinkButton,
  Notice,
  PageBanner,
  Skeleton,
} from "@/components/ui";
import { dateTime } from "@/lib/format";
import { mutate, request } from "@/services/api";
import type { Bulletin, EmailAction } from "@/types/workflows";

const DID: Record<string, string> = {
  submit: "Submitted",
  approve: "Approved",
  reject: "Rejected",
  publish: "Published",
};

const DONE: Record<string, string> = {
  approved: "Approved. The approved text and maps are sealed.",
  rejected: "Rejected. The forecaster can make a revised draft.",
  published: "Published.",
};

function next(bulletin: Bulletin): string {
  const sent = bulletin.notification?.sent?.length ?? 0;
  if (bulletin.status === "approved")
    return sent
      ? "The publishers have been emailed a link to publish it."
      : "It can be published from the bulletin page.";
  if (bulletin.status === "published")
    return sent ? "The bulletin has been sent to the distribution list." : "";
  return "";
}

export default function BulletinDecision() {
  const [token, setToken] = useState<string | null>(null);
  const [link, setLink] = useState<EmailAction | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Bulletin | null>(null);

  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("token");
    setToken(value);
    if (!value) {
      setError("This page opens from the link in a bulletin email.");
      return;
    }
    request<EmailAction>(
      `/bulletins/email-action?token=${encodeURIComponent(value)}`,
    )
      .then(setLink)
      .catch((e) => setError((e as Error).message));
  }, []);

  const decide = async (decision: "approve" | "reject" | "publish") => {
    if (!token) return;
    if (decision === "reject" && !note.trim()) {
      setError("Give a reason for the rejection.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      setResult(
        await mutate<Bulletin>("/bulletins/email-action", {
          token,
          decision,
          name: name.trim() || null,
          comment: note.trim() || null,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const bulletin = link?.bulletin;
  return (
    <div className="page">
      <div className="wrap decision">
        <PageBanner
          compact
          title={
            link?.step === "publish"
              ? "Publish the bulletin"
              : "Review the bulletin"
          }
          crumbs={[
            { label: "Bulletin", href: "/bulletins" },
            { label: "Decision" },
          ]}
        />
        {!link && !error && <Skeleton height={260} />}
        {error && !link && <ErrorState message={error} />}
        {bulletin && (
          <Card
            eyebrow={bulletin.period ?? "Weekly bulletin"}
            title={bulletin.title}
            subtitle={`Sent to ${link.email}`}
          >
            {bulletin.headline && (
              <p className="decision-lead">{bulletin.headline}</p>
            )}
            <div className="decision-links">
              <LinkButton
                href={`/api/bulletins/${bulletin.id}/export?inline=true`}
                variant="outline"
              >
                <Globe2 size={16} /> Read the bulletin
              </LinkButton>
              <LinkButton
                href={`/api/bulletins/${bulletin.id}/export?format=docx`}
                variant="outline"
              >
                <FileDown size={16} /> Word document
              </LinkButton>
            </div>
            {result ? (
              <Notice tone={result.status === "rejected" ? "amber" : "green"}>
                {DONE[result.status] ?? "Done."} {next(result)}{" "}
                <Link href={`/bulletins?id=${bulletin.id}`}>
                  Open the bulletin page
                </Link>
              </Notice>
            ) : link.decisions.length === 0 ? (
              <Notice tone="amber">
                {link.reason}{" "}
                <Link href={`/bulletins?id=${bulletin.id}`}>
                  Open the bulletin page
                </Link>
              </Notice>
            ) : (
              <form
                className="decision-form"
                onSubmit={(e) => e.preventDefault()}
              >
                <label className="field">
                  Your name
                  <input
                    value={name}
                    maxLength={60}
                    placeholder="Shown with your decision"
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <label className="field">
                  {link.decisions.includes("reject")
                    ? "Note (needed to reject)"
                    : "Note"}
                  <textarea
                    rows={3}
                    value={note}
                    maxLength={1000}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </label>
                {error && <Notice tone="red">{error}</Notice>}
                <div className="decision-actions">
                  {link.decisions.includes("approve") && (
                    <Button disabled={busy} onClick={() => decide("approve")}>
                      Approve
                    </Button>
                  )}
                  {link.decisions.includes("publish") && (
                    <Button
                      variant="amber"
                      disabled={busy}
                      onClick={() => decide("publish")}
                    >
                      Publish
                    </Button>
                  )}
                  {link.decisions.includes("reject") && (
                    <Button
                      variant="outline"
                      disabled={busy}
                      onClick={() => decide("reject")}
                    >
                      Reject
                    </Button>
                  )}
                </div>
              </form>
            )}
            {(result ?? bulletin).reviews.length > 0 && (
              <ul className="decision-history">
                {(result ?? bulletin).reviews.map((review, i) => (
                  <li key={i}>
                    <strong>{DID[review.action] ?? review.action}</strong> by{" "}
                    {review.actor}, {dateTime(review.timestamp)}
                    {review.comment ? `: ${review.comment}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}
