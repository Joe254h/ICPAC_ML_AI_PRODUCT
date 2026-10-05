"use client";
import { useEffect, useState } from "react";
import { FilePlus2, Download, GitCompareArrows } from "lucide-react";
import { mutate, request } from "@/services/api";
import type { Selection } from "@/types";
import type { Bulletin } from "@/types/workflows";
import ReviewDialog from "@/components/review-dialog";
import Sources from "@/components/sources";
export default function Bulletins({ selection }: { selection: Selection }) {
  const [rows, setRows] = useState<Bulletin[]>([]),
    [active, setActive] = useState<Bulletin | null>(null),
    [pending, setPending] = useState(false),
    [error, setError] = useState(""),
    [action, setAction] = useState<string | null>(null),
    [compareId, setCompareId] = useState(""),
    [comparison, setComparison] = useState<{
      left: Bulletin;
      right: Bulletin;
      changed_selection: string[];
      facts_identical: boolean;
    } | null>(null);
  async function load() {
    setRows(await request("/bulletins"));
  }
  useEffect(() => {
    request<Bulletin[]>("/bulletins")
      .then((data) => {
        setRows(data);
        setActive(data[0] ?? null);
      })
      .catch((e) => setError(e.message));
  }, []);
  async function generate(parent?: Bulletin) {
    setPending(true);
    setError("");
    try {
      const draft = await mutate<Bulletin>(
        "/bulletins/generate" + (parent ? "?parent_id=" + parent.id : ""),
        parent?.selection ?? selection,
      );
      setActive(draft);
      setComparison(null);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Bulletin workspace</h2>
            <p>
              Frozen forecast facts → consistency check → forecaster review →
              export
            </p>
          </div>
          <button
            className="button primary"
            disabled={pending}
            onClick={() => generate()}
          >
            <FilePlus2 size={15} />
            {pending ? "Generating…" : "Generate draft"}
          </button>
        </div>
        <div className="grounding-bar">
          Publication records stay in this local demonstration. No bulletin is
          distributed externally.
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="bulletin-workspace">
          <div className="bulletin-list">
            <small>RECENT DRAFTS</small>
            {rows.map((b) => (
              <button
                className={active?.id === b.id ? "chosen" : ""}
                key={b.id}
                onClick={() => {
                  setActive(b);
                  setComparison(null);
                  setCompareId("");
                }}
              >
                <strong>{b.title}</strong>
                <span
                  className={
                    "badge " +
                    (b.status === "approved" || b.status === "published"
                      ? "green"
                      : "amber")
                  }
                >
                  {b.status.replaceAll("_", " ")}
                </span>
                <small>{new Date(b.created_at).toLocaleString()}</small>
              </button>
            ))}
            {!rows.length && (
              <p>
                Create a draft from the selected forecast. Source fields and its
                map will be frozen for review.
              </p>
            )}
          </div>
          <div className="bulletin-preview">
            {active ? (
              <>
                <div className="preview-heading">
                  <div>
                    <span
                      className={
                        "badge " +
                        (active.status === "approved" ? "green" : "amber")
                      }
                    >
                      {active.status.replaceAll("_", " ")}
                    </span>
                    <h3>{active.title}</h3>
                    <small>
                      {active.facts.period} · {active.selection.observation}
                    </small>
                  </div>
                  <span className="badge green">
                    Consistency {active.consistency.status}
                  </span>
                </div>
                <div className="narrative">{active.text}</div>
                {active.fallback && (
                  <p className="subtle-alert">{active.fallback}</p>
                )}
                <details className="frozen-map">
                  <summary>View frozen forecast map</summary>
                  <img
                    alt="Frozen bulletin forecast map"
                    src={"/api/bulletins/" + active.id + "/map"}
                  />
                </details>
                <Sources sources={active.sources} />
                <div className="action-row">
                  {active.status === "draft" && (
                    <button
                      className="button primary"
                      onClick={() => setAction("submit")}
                    >
                      Submit for review
                    </button>
                  )}
                  {active.status === "under_review" && (
                    <>
                      <button
                        className="button primary"
                        onClick={() => setAction("approve")}
                      >
                        Approve bulletin
                      </button>
                      <button
                        className="button secondary"
                        onClick={() => setAction("reject")}
                      >
                        Reject bulletin
                      </button>
                    </>
                  )}
                  {active.status === "approved" && (
                    <button
                      className="button primary"
                      onClick={() => setAction("publish")}
                    >
                      Record demo publication
                    </button>
                  )}
                  <button
                    className="button secondary"
                    disabled={pending}
                    onClick={() => generate(active)}
                  >
                    Create revision
                  </button>
                  <a
                    className="button secondary"
                    href={"/api/bulletins/" + active.id + "/export"}
                  >
                    <Download size={14} />
                    Export HTML
                  </a>
                </div>
                <details>
                  <summary>Provenance and review history</summary>
                  <pre>
                    {JSON.stringify(
                      {
                        facts_checksum: active.facts_checksum,
                        provenance: active.facts.provenance,
                        reviews: active.reviews,
                      },
                      null,
                      2,
                    )}
                  </pre>
                </details>
                {rows.length > 1 && (
                  <div className="compare-controls">
                    <label>
                      Compare with
                      <select
                        aria-label="Compare bulletin"
                        value={compareId}
                        onChange={(e) => setCompareId(e.target.value)}
                      >
                        <option value="">Select another draft</option>
                        {rows
                          .filter((b) => b.id !== active.id)
                          .map((b) => (
                            <option key={b.id} value={b.id}>
                              {b.title} · {b.id.slice(0, 6)}
                            </option>
                          ))}
                      </select>
                    </label>
                    <button
                      className="button secondary"
                      disabled={!compareId}
                      onClick={async () => {
                        try {
                          setComparison(
                            await request(
                              "/bulletins/compare?left=" +
                                active.id +
                                "&right=" +
                                compareId,
                            ),
                          );
                        } catch (e) {
                          setError((e as Error).message);
                        }
                      }}
                    >
                      <GitCompareArrows size={14} />
                      Compare drafts
                    </button>
                  </div>
                )}
              </>
            ) : (
              <div className="empty-workflow">
                <FilePlus2 size={30} />
                <h3>A reviewed narrative starts with evidence</h3>
                <p>
                  Choose a cycle, model, observation source and country, then
                  generate a draft.
                </p>
              </div>
            )}
          </div>
        </div>
      </section>
      {comparison && (
        <section className="panel">
          <div className="panel-head">
            <h2>Draft comparison</h2>
            <span className="badge amber">
              Changed:{" "}
              {comparison.changed_selection.join(", ") || "No selector changes"}
            </span>
          </div>
          <div className="draft-comparison">
            {[comparison.left, comparison.right].map((b) => (
              <div key={b.id}>
                <h3>{b.title}</h3>
                <span className="badge amber">{b.status}</span>
                <div className="narrative">{b.text}</div>
              </div>
            ))}
          </div>
        </section>
      )}
      {action && active && (
        <ReviewDialog
          title={
            {
              submit: "Submit draft for review",
              approve: "Approve bulletin",
              reject: "Reject bulletin",
              publish: "Record demo publication",
            }[action] ?? action
          }
          description={
            "Confirm " +
            action +
            " for this frozen draft. Review its data sources, period, QC, units and narrative. Publication creates a local demo record."
          }
          onClose={() => setAction(null)}
          onSubmit={async (review) => {
            const updated = await mutate<Bulletin>(
              "/bulletins/" + active.id + "/" + action,
              review,
            );
            setActive(updated);
            await load();
          }}
        />
      )}
    </>
  );
}
