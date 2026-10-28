"use client";
/** Forecaster Copilot: questions about the latest forecast, answered from its own numbers. */
import Link from "next/link";
import Markdown from "@/components/markdown";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  ArrowDown,
  ArrowLeft,
  ArrowUp,
  BarChart3,
  Ellipsis,
  FileText,
  FileUp,
  KeyRound,
  LoaderCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Paperclip,
  Pencil,
  RefreshCw,
  SquarePen,
  Trash2,
  X,
} from "lucide-react";
import { openStaffAccess } from "@/components/bulletin-access";
import { Button, Notice, PageBanner } from "@/components/ui";
import { cx } from "@/components/ui";
import { LAYER_TEXT, layersOf, ofRecord } from "@/features/operational/shared";
import { day, num, relativeDay, shortPeriod, signed } from "@/lib/format";
import { mutate, request, upload, uploadFile } from "@/services/api";
import { useApi } from "@/services/hooks";
import { useStaff } from "@/services/staff";
import type { ForecastDetail, ForecastRun, Variant } from "@/types/operational";
import { useActor } from "@/lib/actor";
import type {
  ChatAnswer,
  ChatBulletin,
  ChatComparison,
  ChatContext,
  ChatAttachment,
  ChatMessage,
  ChatSession,
  Source,
} from "@/types/workflows";

const SUGGESTIONS = [
  "Summarise this week's forecast for the region.",
  "Explain the forecast for Kenya.",
  "Show this week's bulletin.",
  "How does El Niño affect the October–December rains?",
];
const BULLETIN_STATUS: Record<ChatBulletin["status"], string> = {
  draft: "Draft",
  under_review: "Under review",
  approved: "Approved",
  published: "Published",
  rejected: "Rejected",
};

/** A weekly bulletin draft in the conversation: what a new version changed is marked. */
/** Another model's forecast next to ICPAC's and, once observed, both against CHIRPS. */
function ComparisonCard({ comparison }: { comparison: ChatComparison }) {
  return (
    <section
      className="chat-bulletin chat-comparison"
      aria-label={`${comparison.name} compared with ICPAC`}
    >
      <header>
        <BarChart3 size={16} aria-hidden />
        <strong>{comparison.name}</strong>
        <span className="chat-bulletin-meta">
          {comparison.period} ·{" "}
          {comparison.status === "available"
            ? "Verified against CHIRPS"
            : "Waiting for observations"}
        </span>
      </header>
      <p className="chat-bulletin-change">{comparison.verdict}</p>
      {comparison.scores.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Forecast</th>
                <th className="num">MAE</th>
                <th className="num">RMSE</th>
                <th className="num">Bias</th>
                <th className="num">r</th>
              </tr>
            </thead>
            <tbody>
              {comparison.scores.map((score) => (
                <tr key={score.label}>
                  <td className="strong">
                    {score.label}{" "}
                    {score.closest && (
                      <span className="chat-bulletin-tag">Closest</span>
                    )}
                  </td>
                  <td className="num">{num(score.mae_mm, 2)} mm</td>
                  <td className="num">{num(score.rmse_mm, 2)} mm</td>
                  <td className="num">{signed(score.bias_mm, 2)} mm</td>
                  <td className="num">{num(score.correlation, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {comparison.countries.length > 0 && (
        <details className="chat-details chat-comparison-countries">
          <summary>Country by country</summary>
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Country</th>
                  <th className="num">{comparison.name} (mm)</th>
                  <th className="num">
                    ICPAC {comparison.versus?.main_layer ?? ""} (mm)
                  </th>
                  {comparison.status === "available" && (
                    <>
                      <th className="num">Observed (mm)</th>
                      <th>Closer</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {comparison.countries.map((row) => (
                  <tr key={row.country}>
                    <td className="strong">{row.country}</td>
                    <td className="num">{num(row.theirs_mean_mm, 1)}</td>
                    <td className="num">{num(row.ours_mean_mm, 1)}</td>
                    {comparison.status === "available" && (
                      <>
                        <td className="num">{num(row.observed_mean_mm, 1)}</td>
                        <td>
                          {row.closer === "theirs"
                            ? comparison.name
                            : row.closer === "ours"
                              ? "ICPAC"
                              : "—"}
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}

function BulletinCard({ bulletin }: { bulletin: ChatBulletin }) {
  return (
    <section
      className="chat-bulletin"
      aria-label={`${bulletin.title}, version ${bulletin.version}`}
    >
      <header>
        <FileText size={16} aria-hidden />
        <strong>{bulletin.title}</strong>
        <span className="chat-bulletin-meta">
          Version {bulletin.version} · {BULLETIN_STATUS[bulletin.status]}
        </span>
      </header>
      {bulletin.edited?.summary && (
        <p className="chat-bulletin-change">{bulletin.edited.summary}</p>
      )}
      {bulletin.sections.map((section) => (
        <div
          key={section.key}
          className={cx("chat-bulletin-section", section.changed && "changed")}
        >
          <h4>
            {section.title}
            {section.changed && (
              <span className="chat-bulletin-tag">
                {section.note ? "Added" : "Changed"}
              </span>
            )}
          </h4>
          {section.why && <p className="why">{section.why}</p>}
          {section.text.map((paragraph, index) => (
            <p key={index}>{paragraph}</p>
          ))}
        </div>
      ))}
      <p className="chat-bulletin-foot">
        The country table and the forecast note are in the Word document. Each
        version is checked and submitted by a forecaster; approval and
        publication need named reviewers.
      </p>
    </section>
  );
}
const STORAGE = "icpac-copilot-session";
const MODEL_NAME = "icpac-upload-model";
const UPLOAD_LIMIT = 4 * 1024 * 1024;
const SIDEBAR = "icpac-copilot-sidebar";
const REGION = "GHA";

function Sources({ sources }: { sources: Source[] }) {
  return (
    <details className="chat-details">
      <summary>Sources ({sources.length})</summary>
      <ul>
        {sources.map((source) => (
          <li key={source.id}>
            <a href={source.url} target="_blank" rel="noreferrer">
              {source.title}
            </a>
            <p>{source.excerpt}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}

/** What an answer rests on, in words: the service's data, or general background. */
function AnswerBasis({ message }: { message: ChatMessage }) {
  const basis = message.evidence ?? [];
  if (message.kind === "general")
    return (
      <div className="chat-basis">
        <span className="basis-chip general">General background</span>
        <span className="basis-note">Not from this week&apos;s forecast</span>
      </div>
    );
  if (!basis.length) return null;
  return (
    <div className="chat-basis">
      <span className="basis-note">Based on</span>
      {basis.map((item) => (
        <span key={item} className="basis-chip">
          {item}
        </span>
      ))}
    </div>
  );
}

function Message({
  message,
  onEdit,
  editable = true,
}: {
  message: ChatMessage;
  /** Ask again with changed words (your own questions only). */
  onEdit?: (text: string) => void;
  /** False while an answer is on its way: the button stays, so nothing above moves. */
  editable?: boolean;
}) {
  const user = message.role === "user";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.text);
  return (
    <article className={cx("chat-message", user ? "user" : "assistant")}>
      {!user && (
        <span className="chat-avatar" aria-hidden>
          <img src="/igad-seal-white.png" alt="" width={22} height={22} />
        </span>
      )}
      <div className="chat-bubble">
        <div className="chat-who">{user ? "You" : "Copilot"}</div>
        {editing ? (
          <form
            className="chat-edit-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (!draft.trim()) return;
              setEditing(false);
              onEdit?.(draft);
            }}
          >
            <textarea
              aria-label="Edited question"
              value={draft}
              maxLength={2000}
              rows={3}
              autoFocus
              onChange={(e) => setDraft(e.target.value)}
            />
            <div>
              <Button
                size="sm"
                type="submit"
                disabled={!draft.trim() || !editable}
              >
                Ask again
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setEditing(false)}
              >
                Cancel
              </Button>
            </div>
            <small>
              The answers after this question are replaced by the new answer.
            </small>
          </form>
        ) : (
          <div className="chat-text">
            {user ? message.text : <Markdown text={message.text} />}
          </div>
        )}
        {!!message.attachments?.length && (
          <ul className="chat-files" aria-label="Attached files">
            {message.attachments.map((file) => (
              <li key={file.id}>
                <FileText size={14} aria-hidden /> {file.name}
              </li>
            ))}
          </ul>
        )}
        {user && onEdit && !editing && (
          <button
            type="button"
            className="chat-edit"
            aria-label="Edit this question"
            title="Edit this question"
            disabled={!editable}
            onClick={() => {
              setDraft(message.text);
              setEditing(true);
            }}
          >
            <Pencil size={13} aria-hidden /> Edit
          </button>
        )}
        {message.bulletin && <BulletinCard bulletin={message.bulletin} />}
        {message.comparison && (
          <ComparisonCard comparison={message.comparison} />
        )}
        {message.images?.map((image) => (
          <img
            key={image.url}
            src={image.url}
            alt={image.alt}
            className="chat-map"
          />
        ))}
        {!!message.links?.length && (
          <div className="chat-links">
            {message.links.map((link) => (
              <Link key={link.url} href={link.url} className="link-amber">
                {link.label} →
              </Link>
            ))}
          </div>
        )}
        {message.fallback && (
          <p className="chat-fallback">
            Answered from the forecast data alone, because the AI assistant did
            not respond:{" "}
            {(
              message.fallback_reason ?? "it could not respond just now"
            ).replace(/\.$/, "")}
            .
          </p>
        )}
        {!user && <AnswerBasis message={message} />}
        {!!message.sources?.length && <Sources sources={message.sources} />}
      </div>
    </article>
  );
}

/** Answer languages: the member states' languages and the region's working languages.
 * Answers in the less-resourced ones need a speaker's review before they are used. */
const LANGUAGES: Record<string, string> = {
  en: "English",
  sw: "Kiswahili",
  am: "Amharic (አማርኛ)",
  so: "Somali (Soomaali)",
  ar: "Arabic (العربية)",
  fr: "French (Français)",
  ti: "Tigrinya (ትግርኛ)",
  om: "Afaan Oromo",
  rw: "Kinyarwanda",
  rn: "Kirundi",
  lg: "Luganda",
};
const LANGUAGE_KEY = "icpac-copilot-language";

export default function Copilot() {
  const [actor] = useActor();
  const [language, setLanguage] = useState("en");
  useEffect(() => {
    try {
      const kept = localStorage.getItem(LANGUAGE_KEY);
      if (kept && kept in LANGUAGES) setLanguage(kept);
    } catch {
      // Storage blocked: English until chosen.
    }
  }, []);
  const chooseLanguage = (code: string) => {
    setLanguage(code);
    try {
      localStorage.setItem(LANGUAGE_KEY, code);
    } catch {
      // The choice lasts for this page.
    }
  };
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [session, setSession] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [context, setContext] = useState<ChatContext | null>(null);
  const [country, setCountry] = useState(REGION);
  /** Empty: the forecast's main layer. */
  const [variant, setVariant] = useState<Variant | "">("");
  const [resetContext, setResetContext] = useState(false);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [error, setError] = useState("");
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  // The conversation list: a sidebar that can be hidden (remembered) on wide screens, a
  // drawer on narrow ones.
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyHidden, setHistoryHidden] = useState(false);
  // Archived conversations: out of the list, kept until deleted.
  const [archived, setArchived] = useState<ChatSession[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  /** The conversation whose options menu is open. */
  const [menu, setMenu] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<ChatSession | null>(null);
  const [removing, setRemoving] = useState(false);
  const stream = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  /** Another model's forecast chosen for upload, with its name and (if undated) week. */
  const [attached, setAttached] = useState<File | null>(null);
  const [modelName, setModelName] = useState("");
  const [weekStart, setWeekStart] = useState("");
  const [uploading, setUploading] = useState(false);
  /** Files attached to the next question. */
  const [files, setFiles] = useState<ChatAttachment[]>([]);
  const [reading, setReading] = useState(false);
  /** The forecast week chosen in the menu, for the next question. */
  const [week, setWeek] = useState("");
  const forecastList = useApi<ForecastRun[]>("/forecasts");
  const stickToBottom = useRef(true);
  const latest = useApi<ForecastDetail>("/forecasts/latest");
  // In staff mode the Copilot answers signed-in staff only: before signing in there is
  // nothing to restore and nothing to retry, only a way to sign in.
  const signInNeeded = useStaff().needsSignIn;

  const adopt = (data: ChatSession) => {
    setSession(data.id);
    setMessages(data.messages ?? []);
    setContext(data.context ?? null);
    setCountry(data.context?.country ?? REGION);
    setVariant(data.context?.variant ?? "");
  };

  useEffect(() => {
    try {
      setHistoryHidden(localStorage.getItem(SIDEBAR) === "hidden");
    } catch {
      // private window: the sidebar starts shown
    }
  }, []);

  const narrow = () => window.matchMedia("(max-width: 900px)").matches;
  const remember = (value: "shown" | "hidden") => {
    try {
      localStorage.setItem(SIDEBAR, value);
    } catch {
      // private window: not remembered
    }
  };
  const showHistory = () => {
    if (narrow()) return setHistoryOpen(true);
    setHistoryHidden(false);
    remember("shown");
  };
  const hideHistory = () => {
    if (narrow()) return setHistoryOpen(false);
    setHistoryHidden(true);
    remember("hidden");
  };

  useEffect(() => {
    let mounted = true;
    request<ChatSession[]>("/chat/sessions")
      .then((data) => mounted && setSessions(data))
      .catch(() => {});
    let id: string | null = null;
    try {
      id = localStorage.getItem(STORAGE);
    } catch {
      id = null;
    }
    if (!id) {
      setRestoring(false);
      return () => {
        mounted = false;
      };
    }
    request<ChatSession>("/chat/sessions/" + encodeURIComponent(id))
      .then((data) => mounted && adopt(data))
      .catch((e) => {
        if (!mounted) return;
        if (e.status === 404) localStorage.removeItem(STORAGE);
        // Signed out: the conversation is still saved and returns after signing in.
        else if (e.status === 401 || e.status === 403) return;
        else {
          setRestoreFailed(true);
          setSession(id);
          setError(
            "The conversation could not be restored. It is still saved; retry below.",
          );
        }
      })
      .finally(() => mounted && setRestoring(false));
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!menu) return;
    const outside = (e: PointerEvent) => {
      const target = e.target as Element | null;
      if (!target?.closest(".history-menu, .history-more")) setMenu(null);
    };
    const escape = (e: KeyboardEvent) => e.key === "Escape" && setMenu(null);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [menu]);

  useEffect(() => {
    if (!deleting) return;
    const escape = (e: KeyboardEvent) =>
      e.key === "Escape" && !removing && setDeleting(null);
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [deleting, removing]);

  // Before the browser paints: a scroll event in between (the browser keeping its place
  // while the page changes) would otherwise read as the reader scrolling away.
  useLayoutEffect(() => {
    if (stickToBottom.current && stream.current)
      stream.current.scrollTop = stream.current.scrollHeight;
  }, [messages, pending, restoring]);

  async function openSession(id: string) {
    if (pending) return;
    setRestoring(true);
    setError("");
    try {
      const data = await request<ChatSession>(
        "/chat/sessions/" + encodeURIComponent(id),
      );
      stickToBottom.current = true;
      setAwayFromBottom(false);
      setRestoreFailed(false);
      adopt(data);
      setResetContext(false);
      setInput("");
      localStorage.setItem(STORAGE, data.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRestoring(false);
    }
  }

  const newest = (a: ChatSession, b: ChatSession) =>
    (b.updated_at ?? b.created_at).localeCompare(a.updated_at ?? a.created_at);

  async function openArchived(open: boolean) {
    setMenu(null);
    setShowArchived(open);
    if (!open) return;
    try {
      setArchived(await request<ChatSession[]>("/chat/sessions?archived=true"));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function archive(item: ChatSession, value: boolean) {
    setMenu(null);
    setError("");
    try {
      await request(
        `/chat/sessions/${encodeURIComponent(item.id)}/archive?archived=${value}`,
        { method: "POST" },
      );
      const moved = { ...item, archived: value };
      if (value) {
        setSessions((old) => old.filter((s) => s.id !== item.id));
        setArchived((old) => [moved, ...old].sort(newest));
        if (item.id === session) newConversation();
      } else {
        setArchived((old) => old.filter((s) => s.id !== item.id));
        setSessions((old) => [moved, ...old].sort(newest));
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(item: ChatSession) {
    setRemoving(true);
    setError("");
    try {
      await request(`/chat/sessions/${encodeURIComponent(item.id)}`, {
        method: "DELETE",
      });
      setSessions((old) => old.filter((s) => s.id !== item.id));
      setArchived((old) => old.filter((s) => s.id !== item.id));
      if (item.id === session) newConversation();
      setDeleting(null);
    } catch (e) {
      setError((e as Error).message);
      setDeleting(null);
    } finally {
      setRemoving(false);
    }
  }

  function newConversation() {
    setMessages([]);
    setSession(null);
    setRestoreFailed(false);
    setContext(null);
    setCountry(REGION);
    setVariant("");
    setResetContext(false);
    setInput("");
    setError("");
    stickToBottom.current = true;
    setAwayFromBottom(false);
    localStorage.removeItem(STORAGE);
    composer.current?.focus();
  }

  async function sendUpload() {
    if (!attached) return;
    setError("");
    if (attached.size > UPLOAD_LIMIT) {
      setError(
        `The file is ${(attached.size / 1024 / 1024).toFixed(1)} MB; the limit is 4 MB. Upload the Week-2 total only (one rainfall field over the region).`,
      );
      return;
    }
    setUploading(true);
    try {
      const params = new URLSearchParams({
        name: modelName.trim(),
        file_name: attached.name,
        ...(weekStart ? { valid_start: weekStart } : {}),
      });
      const record = await upload<{ id: string; name: string }>(
        `/external-forecasts?${params}`,
        attached,
      );
      try {
        localStorage.setItem(MODEL_NAME, modelName.trim());
      } catch {
        // private window: the name is asked again next time
      }
      setAttached(null);
      setWeekStart("");
      await send(
        `Compare the forecast I uploaded (${record.name}) with ICPAC's forecast.`,
        { external_id: record.id },
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function send(
    text: string,
    extra: { external_id?: string; edit_index?: number } = {},
  ) {
    const message = text.trim();
    if (!message || pending || restoring || restoreFailed || reading) return;
    const before = messages;
    const attachments = extra.edit_index === undefined ? files : [];
    setPending(true);
    setError("");
    if (extra.edit_index === undefined) setInput("");
    stickToBottom.current = true;
    setAwayFromBottom(false);
    setMessages((old) => [
      ...(extra.edit_index === undefined
        ? old
        : old.slice(0, extra.edit_index)),
      { role: "user", text: message, attachments },
    ]);
    try {
      const answer = await mutate<ChatAnswer>("/chat", {
        message,
        session_id: session,
        context_mode: "operational",
        country,
        variant: variant || null,
        reset_context: resetContext,
        actor: actor || null,
        language,
        forecast_id: week || null,
        attachment_ids: attachments.map((file) => file.id),
        ...extra,
      });
      if (attachments.length) setFiles([]);
      setWeek("");
      setMessages((old) => [...old, { ...answer, role: "assistant" }]);
      setSession(answer.session_id);
      setContext(answer.context ?? null);
      setCountry(answer.context?.country ?? country);
      if (variant) setVariant(answer.context?.variant ?? variant);
      setResetContext(false);
      localStorage.setItem(STORAGE, answer.session_id);
      const now = new Date().toISOString();
      setSessions((old) => {
        const known = old.find((s) => s.id === answer.session_id);
        return [
          {
            id: answer.session_id,
            title: known?.title ?? message.slice(0, 80),
            created_at: known?.created_at ?? now,
            updated_at: now,
            message_count: messages.length + 2,
            context: answer.context,
          },
          ...old.filter((s) => s.id !== answer.session_id),
        ];
      });
      // Asking in an archived conversation brings it back to the list.
      setArchived((old) => old.filter((s) => s.id !== answer.session_id));
    } catch (e) {
      if (extra.edit_index === undefined) {
        setMessages((old) => old.slice(0, -1));
        setInput((draft) => draft || message);
      } else setMessages(before);
      setError((e as Error).message);
    } finally {
      setPending(false);
      composer.current?.focus();
    }
  }

  /** A file of any format for the next question; a NetCDF forecast goes to the forecast
   * comparison instead. */
  async function attachFile(file: File) {
    if (/\.(nc|nc4|netcdf)$/i.test(file.name)) {
      setAttached(file);
      try {
        setModelName((name) => name || localStorage.getItem(MODEL_NAME) || "");
      } catch {
        // private window: the name is typed each time
      }
      return;
    }
    setReading(true);
    setError("");
    try {
      const record = await uploadFile<ChatAttachment>(
        `/chat/attachments?name=${encodeURIComponent(file.name)}`,
        file,
      );
      setFiles((old) => [...old, record].slice(-5));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setReading(false);
    }
  }

  const forecast = latest.data;
  const pinned = context?.forecast_id && !resetContext ? context : null;
  const layers = forecast ? layersOf(forecast) : [];
  const countries = forecast?.countries.map((row) => row.country) ?? [];
  if (country !== REGION && !countries.includes(country))
    countries.push(country);
  const locked = pending || restoring || signInNeeded;
  const span =
    pinned?.valid_start && pinned.valid_end
      ? [pinned.valid_start, pinned.valid_end]
      : forecast
        ? [forecast.valid_start, forecast.valid_end]
        : null;

  const shown = showArchived ? archived : sessions.slice(0, 50);
  // The weeks to choose from: each ECMWF run's forecast, and the conversation's own if it
  // is about an earlier version.
  const listed = Array.isArray(forecastList.data) ? forecastList.data : [];
  const weeks = ofRecord(listed).filter((r) => !r.synthetic);
  const own = listed.find((r) => r.forecast_id === pinned?.forecast_id);
  if (own && !weeks.includes(own)) weeks.push(own);
  const shownWeek =
    week ||
    pinned?.forecast_id ||
    forecast?.forecast_id ||
    weeks[0]?.forecast_id ||
    "";

  const startNew = () => {
    newConversation();
    setHistoryOpen(false);
  };

  return (
    <div className="page copilot-page">
      <div className="wrap">
        <PageBanner
          compact
          title="Forecaster Copilot"
          crumbs={[{ label: "Copilot" }]}
          subtitle="Questions about this week's forecast, observed rainfall and verification, and about weather and climate."
        />
        <div
          className={cx(
            "copilot",
            historyOpen && "history-open",
            historyHidden && "history-hidden",
          )}
        >
          <aside
            id="copilot-history"
            className="copilot-history"
            aria-label="Conversations"
          >
            <div className="history-head">
              <button
                type="button"
                className="history-new"
                disabled={locked}
                onClick={() => {
                  setHistoryOpen(false);
                  startNew();
                }}
              >
                <SquarePen size={16} aria-hidden /> New conversation
              </button>
              <button
                type="button"
                className="history-close"
                aria-label="Hide conversations"
                title="Hide conversations"
                aria-controls="copilot-history"
                onClick={hideHistory}
              >
                <PanelLeftClose size={19} />
              </button>
            </div>
            <h2 className="history-heading">
              {showArchived ? "Archived conversations" : "Conversations"}
            </h2>
            {!shown.length ? (
              <p className="history-empty">
                {showArchived
                  ? "No archived conversations."
                  : "Your conversations are kept here."}
              </p>
            ) : (
              <nav
                className="history-list"
                aria-label={
                  showArchived
                    ? "Archived conversations"
                    : "Saved conversations"
                }
              >
                {shown.map((item) => (
                  <div
                    key={item.id}
                    className={cx(
                      "history-item",
                      menu === item.id && "menu-open",
                    )}
                  >
                    <button
                      type="button"
                      className="history-open"
                      disabled={locked}
                      aria-current={item.id === session ? "true" : undefined}
                      onClick={() => {
                        setHistoryOpen(false);
                        openSession(item.id);
                      }}
                    >
                      <span className="history-title">{item.title}</span>
                      <span className="history-meta">
                        {relativeDay(item.updated_at ?? item.created_at)}
                        {" · "}
                        {item.message_count} messages
                      </span>
                    </button>
                    <button
                      type="button"
                      className="history-more"
                      aria-label={`Options for ${item.title}`}
                      title="Archive or delete"
                      aria-haspopup="menu"
                      aria-expanded={menu === item.id}
                      disabled={locked}
                      onClick={() =>
                        setMenu((open) => (open === item.id ? null : item.id))
                      }
                    >
                      <Ellipsis size={17} />
                    </button>
                    {menu === item.id && (
                      <div className="history-menu" role="menu">
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => archive(item, !showArchived)}
                        >
                          {showArchived ? (
                            <>
                              <ArchiveRestore size={16} aria-hidden /> Restore
                            </>
                          ) : (
                            <>
                              <Archive size={16} aria-hidden /> Archive
                            </>
                          )}
                        </button>
                        <button
                          type="button"
                          role="menuitem"
                          className="danger"
                          onClick={() => {
                            setMenu(null);
                            setDeleting(item);
                          }}
                        >
                          <Trash2 size={16} aria-hidden /> Delete
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </nav>
            )}
            <button
              type="button"
              className="history-shelf"
              onClick={() => openArchived(!showArchived)}
            >
              {showArchived ? (
                <>
                  <ArrowLeft size={16} aria-hidden /> Back to conversations
                </>
              ) : (
                <>
                  <Archive size={16} aria-hidden /> Archived conversations
                </>
              )}
            </button>
          </aside>
          <section className="chat-card" aria-label="Conversation">
            <header className="chat-context">
              <button
                type="button"
                className="context-icon history-toggle"
                aria-label="Show conversations"
                title="Show conversations"
                aria-controls="copilot-history"
                aria-expanded={!historyHidden}
                onClick={showHistory}
              >
                <PanelLeftOpen size={19} />
              </button>
              <label className="context-forecast context-select">
                <span>Forecast week</span>
                {weeks.length ? (
                  <select
                    aria-label="Forecast week"
                    value={shownWeek}
                    disabled={locked}
                    onChange={(e) => setWeek(e.target.value)}
                  >
                    {weeks.map((run, i) => (
                      <option key={run.forecast_id} value={run.forecast_id}>
                        {shortPeriod(
                          run.valid_start,
                          new Date(
                            new Date(run.valid_end).getTime() - 86_400_000,
                          ).toISOString(),
                        )}
                        {i === 0
                          ? " · newest"
                          : ` · run ${day(run.initialization)}`}
                      </option>
                    ))}
                  </select>
                ) : (
                  <strong>
                    {span
                      ? shortPeriod(
                          span[0],
                          new Date(
                            new Date(span[1]).getTime() - 86_400_000,
                          ).toISOString(),
                        )
                      : latest.loading
                        ? "Loading…"
                        : "None yet"}
                  </strong>
                )}
              </label>
              <label className="context-select context-area">
                <span>Area</span>
                <select
                  aria-label="Conversation country"
                  value={country}
                  disabled={locked}
                  onChange={(e) => setCountry(e.target.value)}
                >
                  <option value={REGION}>Whole region</option>
                  {countries.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="context-select context-layer">
                <span>Layer</span>
                <select
                  aria-label="Conversation rainfall method"
                  value={variant}
                  disabled={locked}
                  onChange={(e) => setVariant(e.target.value as Variant | "")}
                >
                  <option value="">Issued forecast</option>
                  {layers.map((layer) => (
                    <option key={layer} value={layer}>
                      {LAYER_TEXT[layer].title}
                    </option>
                  ))}
                </select>
              </label>
              <label className="context-select context-language">
                <span>Language</span>
                <select
                  aria-label="Answer language"
                  value={language}
                  onChange={(e) => chooseLanguage(e.target.value)}
                >
                  {Object.entries(LANGUAGES).map(([code, name]) => (
                    <option key={code} value={code}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <Link href="/bulletin" className="context-link">
                <FileText size={16} aria-hidden /> Bulletin
              </Link>
              <button
                type="button"
                className="context-icon context-new"
                aria-label="New conversation"
                title="New conversation"
                disabled={locked}
                onClick={startNew}
              >
                <SquarePen size={18} />
              </button>
            </header>
            {pinned &&
              forecast &&
              pinned.forecast_id !== forecast.forecast_id && (
                <div className="chat-pinned">
                  This conversation is about an earlier forecast.
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={locked}
                    onClick={() => {
                      setResetContext(true);
                      latest.reload();
                    }}
                  >
                    <RefreshCw size={14} /> Use the latest
                  </Button>
                </div>
              )}
            {latest.status === 404 && (
              <div className="chat-pinned">
                No forecast has been issued yet; general questions still work.{" "}
                <Link href="/data/runs">Run the weekly cycle</Link>
              </div>
            )}
            <div
              ref={stream}
              className="chat-stream"
              role="log"
              aria-label="Conversation messages"
              aria-live="polite"
              aria-busy={locked}
              onScroll={() => {
                const node = stream.current;
                if (!node) return;
                stickToBottom.current =
                  node.scrollHeight - node.scrollTop - node.clientHeight < 80;
                setAwayFromBottom(!stickToBottom.current);
              }}
            >
              {signInNeeded ? (
                <div className="chat-welcome chat-locked">
                  <span className="modal-icon" aria-hidden>
                    <KeyRound size={20} />
                  </span>
                  <h2>Sign in to use the Copilot</h2>
                  <p>
                    The Copilot answers questions about this week&apos;s
                    forecast, observed rainfall and verification for ICPAC
                    staff. Sign in with your personal key; your conversations
                    stay private to it.
                  </p>
                  <Button onClick={openStaffAccess}>Sign in</Button>
                </div>
              ) : restoring ? (
                <p role="status" className="chat-status">
                  <LoaderCircle size={16} className="spin" /> Loading the
                  conversation…
                </p>
              ) : !messages.length ? (
                <div className="chat-welcome">
                  <h2>What would you like to know?</h2>
                  <p>
                    Ask about a country, the region or a forecast layer, then
                    follow up with “And Somalia?”. The conversation stays on the
                    same forecast until you start a new one.
                  </p>
                  <div className="suggestions">
                    {SUGGESTIONS.map((text) => (
                      <button
                        key={text}
                        type="button"
                        disabled={locked || restoreFailed}
                        onClick={() => send(text)}
                      >
                        {text}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                messages.map((message, index) => (
                  <Message
                    key={`${index}-${message.text}`}
                    message={message}
                    onEdit={
                      message.role === "user"
                        ? (text) => send(text, { edit_index: index })
                        : undefined
                    }
                    editable={!locked}
                  />
                ))
              )}
              {pending && (
                <p className="chat-status" role="status">
                  <LoaderCircle size={16} className="spin" /> Looking at the
                  forecast…
                </p>
              )}
            </div>
            {awayFromBottom && (
              <button
                type="button"
                className="chat-jump"
                onClick={() => {
                  stickToBottom.current = true;
                  setAwayFromBottom(false);
                  if (stream.current)
                    stream.current.scrollTop = stream.current.scrollHeight;
                }}
              >
                <ArrowDown size={14} /> Latest message
              </button>
            )}
            {error && (
              <div className="chat-error" role="alert">
                <Notice tone="red">{error}</Notice>
                {restoreFailed && session && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => openSession(session)}
                  >
                    Retry loading the conversation
                  </Button>
                )}
              </div>
            )}
            {attached && (
              <div
                className="chat-upload"
                role="group"
                aria-label="Upload another model's forecast"
              >
                <p className="chat-upload-file">
                  <FileUp size={16} aria-hidden />{" "}
                  <strong>{attached.name}</strong>
                  <span>{(attached.size / 1024 / 1024).toFixed(1)} MB</span>
                </p>
                <label>
                  Model name
                  <input
                    value={modelName}
                    maxLength={80}
                    placeholder="For example: Colleague CNN v2"
                    onChange={(e) => setModelName(e.target.value)}
                  />
                </label>
                <label>
                  Week starts
                  <input
                    type="date"
                    value={weekStart}
                    onChange={(e) => setWeekStart(e.target.value)}
                  />
                  <small>Only needed if the file has no dates</small>
                </label>
                <div className="chat-upload-actions">
                  <Button
                    size="sm"
                    onClick={sendUpload}
                    disabled={uploading || modelName.trim().length < 2}
                  >
                    {uploading ? "Reading the file…" : "Upload and compare"}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={uploading}
                    onClick={() => setAttached(null)}
                  >
                    Cancel
                  </Button>
                </div>
                <p className="chat-upload-note">
                  A NetCDF file with the Week-2 rainfall total, or its seven
                  daily totals, on a latitude-longitude grid; up to 4 MB. It is
                  compared with ICPAC&apos;s forecast of the same week and, once
                  CHIRPS covers the week, both are scored against it.
                </p>
              </div>
            )}
            {files.length > 0 && (
              <ul
                className="chat-pending-files"
                aria-label="Files for the next question"
              >
                {files.map((file) => (
                  <li key={file.id}>
                    <FileText size={14} aria-hidden />
                    <span>{file.name}</span>
                    <small>
                      {file.kind === "image"
                        ? "image"
                        : file.kind === "text"
                          ? (file.note ??
                            `${Math.round((file.characters ?? 0) / 1000)}k characters read`)
                          : "kept, not readable as text"}
                    </small>
                    <button
                      type="button"
                      aria-label={`Remove ${file.name}`}
                      onClick={() =>
                        setFiles((old) => old.filter((f) => f.id !== file.id))
                      }
                    >
                      <X size={13} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <form
              className="chat-compose"
              onSubmit={(e) => {
                e.preventDefault();
                send(input);
              }}
            >
              <button
                type="button"
                className="chat-attach"
                aria-label="Attach a file"
                title="Attach a file: documents, spreadsheets, PDFs, images or text; a NetCDF forecast is compared with ICPAC's"
                disabled={
                  pending ||
                  uploading ||
                  reading ||
                  restoring ||
                  restoreFailed ||
                  signInNeeded
                }
                onClick={() => fileInput.current?.click()}
              >
                {reading ? (
                  <LoaderCircle size={18} className="spin" />
                ) : (
                  <Paperclip size={18} />
                )}
              </button>
              <input
                ref={fileInput}
                type="file"
                hidden
                data-testid="forecast-file"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) void attachFile(file);
                }}
              />
              <label className="sr-only" htmlFor="copilot-question">
                Ask Forecaster Copilot
              </label>
              <textarea
                ref={composer}
                id="copilot-question"
                rows={1}
                maxLength={2000}
                disabled={restoring || restoreFailed || signInNeeded}
                placeholder={
                  signInNeeded
                    ? "Sign in to ask the Copilot"
                    : "Ask about the forecast"
                }
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  e.target.style.height = "auto";
                  e.target.style.height = `${Math.min(e.target.scrollHeight, 180)}px`;
                }}
                onKeyDown={(e) => {
                  if (
                    e.key === "Enter" &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing
                  ) {
                    e.preventDefault();
                    send(input);
                  }
                }}
              />
              <button
                type="submit"
                className="chat-send"
                aria-label="Send"
                disabled={
                  pending ||
                  restoring ||
                  restoreFailed ||
                  signInNeeded ||
                  !input.trim()
                }
              >
                <ArrowUp size={18} />
              </button>
            </form>
          </section>
          {historyOpen && (
            <button
              type="button"
              className="history-scrim"
              aria-label="Close conversations"
              onClick={() => setHistoryOpen(false)}
            />
          )}
        </div>
      </div>
      {deleting && (
        <div
          className="modal-backdrop"
          onClick={() => !removing && setDeleting(null)}
        >
          <div
            className="modal confirm-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="delete-title">Delete this conversation?</h2>
            <p>
              <strong>{deleting.title}</strong> and its messages will be deleted
              for good. To keep it out of the list instead, archive it.
            </p>
            <div className="row">
              <Button
                variant="outline"
                autoFocus
                disabled={removing}
                onClick={() => setDeleting(null)}
              >
                Cancel
              </Button>
              <Button
                variant="danger"
                disabled={removing}
                onClick={() => remove(deleting)}
              >
                {removing ? "Deleting…" : "Delete"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
