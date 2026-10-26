"use client";
/**
 * Staff sign-in: a header button that opens a dialog for the personal staff key. The key
 * stays in this tab's memory only; signing in or out re-renders the page ("staff-access").
 * Any page can open the dialog with the "open-staff-access" event.
 */
import { useEffect, useRef, useState } from "react";
import { KeyRound, LogOut, UserRound, X } from "lucide-react";
import { Button, Notice } from "@/components/ui";
import {
  getBulletinOperatorKey,
  getStaffUser,
  request,
  setBulletinOperatorKey,
  setStaffUser,
} from "@/services/api";
import type { StaffUser } from "@/services/api";

const ROLE_WORDS: Record<string, string> = {
  admin: "administrator",
  operator: "operator",
  reviewer: "reviewer",
  publisher: "publisher",
  chat: "Copilot",
};

/** Ask the header to open the staff sign-in dialog. */
export function openStaffAccess() {
  window.dispatchEvent(new Event("open-staff-access"));
}

function Dialog({
  user,
  onClose,
}: {
  user: StaffUser | null;
  onClose: () => void;
}) {
  const [key, setKey] = useState(getBulletinOperatorKey);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const field = useRef<HTMLInputElement>(null);
  useEffect(() => {
    field.current?.focus();
    const escape = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [onClose]);

  const changed = () => window.dispatchEvent(new Event("staff-access"));
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form
        className="modal staff-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="staff-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={async (e) => {
          e.preventDefault();
          setPending(true);
          setError("");
          try {
            const me = await request<StaffUser>("/access/me", {
              headers: { Authorization: `Bearer ${key.trim()}` },
            });
            setBulletinOperatorKey(key.trim());
            setStaffUser(me);
            changed();
            onClose();
          } catch (failure) {
            setError((failure as Error).message);
          } finally {
            setPending(false);
          }
        }}
      >
        <div className="modal-head">
          <span className="modal-icon" aria-hidden>
            <KeyRound size={20} />
          </span>
          <div>
            <h2 id="staff-title">Staff access</h2>
            <p>
              Forecasters and reviewers sign in with their personal key to run
              forecasts, review bulletins and use the Copilot.
            </p>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="Close"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        {user && (
          <div className="signed-in">
            <UserRound size={18} aria-hidden />
            <span>
              Signed in as <strong>{user.name}</strong>
              {user.roles.length > 0 &&
                ` · ${user.roles.map((r) => ROLE_WORDS[r] ?? r).join(", ")}`}
            </span>
          </div>
        )}
        <label className="field">
          Staff access key
          <input
            ref={field}
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={key}
            onChange={(e) => setKey(e.target.value)}
          />
          <span className="hint">
            Kept in this tab only: reloading or closing it signs you out. Your
            Copilot conversations are private to your key.
          </span>
        </label>
        {error && <Notice tone="red">{error}</Notice>}
        <div className="row">
          {user && (
            <Button
              variant="outline"
              className="push-left"
              onClick={() => {
                setKey("");
                setBulletinOperatorKey("");
                setStaffUser(null);
                changed();
                onClose();
              }}
            >
              <LogOut size={16} aria-hidden /> Disconnect
            </Button>
          )}
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <button
            type="submit"
            className="btn btn-green"
            disabled={pending || !key.trim()}
          >
            {pending ? "Checking…" : "Connect"}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function StaffAccess() {
  const [open, setOpen] = useState(false);
  const [user, setUser] = useState<StaffUser | null>(getStaffUser);
  useEffect(() => {
    const show = () => setOpen(true);
    const changed = () => setUser(getStaffUser());
    window.addEventListener("open-staff-access", show);
    window.addEventListener("staff-access", changed);
    return () => {
      window.removeEventListener("open-staff-access", show);
      window.removeEventListener("staff-access", changed);
    };
  }, []);
  return (
    <>
      <button
        type="button"
        className={user ? "staff-chip" : "staff-button"}
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-label={user ? `Signed in as ${user.name}` : undefined}
      >
        {user ? (
          <>
            <span className="avatar" aria-hidden>
              {user.name.slice(0, 1).toUpperCase()}
            </span>
            <span className="label">{user.name}</span>
          </>
        ) : (
          <>
            <KeyRound size={15} aria-hidden />
            <span className="label">Staff access</span>
          </>
        )}
      </button>
      {open && <Dialog user={user} onClose={() => setOpen(false)} />}
    </>
  );
}
