"use client";
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
export type Review = { actor: string; comment: string; confirmed: boolean };
export default function ReviewDialog({
  title,
  description,
  onClose,
  onSubmit,
}: {
  title: string;
  description: string;
  onClose: () => void;
  onSubmit: (review: Review) => Promise<void>;
}) {
  const [actor, setActor] = useState(""),
    [comment, setComment] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [pending, setPending] = useState(false),
    [error, setError] = useState("");
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => {
    first.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, [onClose]);
  return (
    <div className="modal-backdrop">
      <form
        className="review-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-title"
        onSubmit={async (e) => {
          e.preventDefault();
          setPending(true);
          setError("");
          try {
            await onSubmit({ actor, comment, confirmed });
            onClose();
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setPending(false);
          }
        }}
      >
        <div className="panel-head">
          <h2 id="review-title">{title}</h2>
          <button
            type="button"
            className="icon-button"
            aria-label="Close review"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        <p className="prose">{description}</p>
        <div className="form-body">
          <label>
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
          <label>
            Review justification
            <textarea
              required
              maxLength={1000}
              rows={3}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              required
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            I have reviewed the evidence and confirm this action.
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <div className="action-row">
            <button
              type="button"
              className="button secondary"
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              className="button primary"
              disabled={
                pending || !confirmed || !actor.trim() || !comment.trim()
              }
            >
              {pending ? "Saving…" : "Confirm action"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
