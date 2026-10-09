"use client";
/** A named, justified and confirmed review decision. */
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button, Notice } from "@/components/ui";
import { useActor } from "@/lib/actor";

export type Review = { actor: string; comment: string; confirmed: boolean };

export default function ReviewDialog({
  title,
  description,
  confirmLabel = "Confirm",
  statement = "I have checked the bulletin, its maps and its source forecast, and confirm this decision.",
  onClose,
  onSubmit,
}: {
  title: string;
  description: string;
  confirmLabel?: string;
  /** What the reviewer confirms having checked. */
  statement?: string;
  onClose: () => void;
  onSubmit: (review: Review) => Promise<void>;
}) {
  const [saved, save] = useActor();
  const [actor, setActor] = useState("");
  const [comment, setComment] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => setActor((a) => a || saved), [saved]);
  useEffect(() => {
    first.current?.focus();
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={async (e) => {
          e.preventDefault();
          setPending(true);
          setError("");
          try {
            save(actor.trim());
            await onSubmit({ actor: actor.trim(), comment, confirmed });
            onClose();
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setPending(false);
          }
        }}
      >
        <div
          style={{ display: "flex", justifyContent: "space-between", gap: 12 }}
        >
          <h2 id="review-title">{title}</h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            style={{
              background: "none",
              border: 0,
              cursor: "pointer",
              color: "var(--muted)",
            }}
          >
            <X size={22} />
          </button>
        </div>
        <p style={{ margin: 0 }}>{description}</p>
        <label className="field">
          Reviewer name
          <input
            ref={first}
            required
            minLength={2}
            maxLength={80}
            value={actor}
            onChange={(e) => setActor(e.target.value)}
          />
        </label>
        <label className="field">
          Justification
          <textarea
            required
            maxLength={1000}
            rows={3}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </label>
        <label
          style={{
            display: "flex",
            gap: 10,
            alignItems: "flex-start",
            fontSize: 15,
          }}
        >
          <input
            type="checkbox"
            required
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
            style={{ marginTop: 5 }}
          />
          {statement}
        </label>
        {error && <Notice tone="red">{error}</Notice>}
        <div className="row">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <button
            type="submit"
            className="btn btn-green"
            disabled={
              pending ||
              !confirmed ||
              actor.trim().length < 2 ||
              !comment.trim()
            }
          >
            {pending ? "Saving…" : confirmLabel}
          </button>
        </div>
      </form>
    </div>
  );
}
