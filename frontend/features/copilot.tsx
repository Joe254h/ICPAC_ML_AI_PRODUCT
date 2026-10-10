"use client";
/** Forecaster Copilot: questions about the latest forecast, answered from its own numbers. */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  FileText,
  History,
  LoaderCircle,
  RefreshCw,
  SquarePen,
  X,
} from "lucide-react";
import { Button, Notice, PageBanner } from "@/components/ui";
import { cx } from "@/components/ui";
import { LAYER_TEXT, layersOf } from "@/features/operational/shared";
import { relativeDay, shortPeriod } from "@/lib/format";
import { mutate, request } from "@/services/api";
import { useApi } from "@/services/hooks";
import type { ForecastDetail, Variant } from "@/types/operational";
import type {
  ChatAnswer,
  ChatContext,
  ChatMessage,
  ChatSession,
  Source,
} from "@/types/workflows";

const SUGGESTIONS = [
  "Summarise this week's forecast for the region.",
  "Explain the forecast for Kenya.",
  "Show the rainfall map for Somalia.",
  "How does El Niño affect the October–December rains?",
];
const STORAGE = "icpac-copilot-session";
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

function Message({ message }: { message: ChatMessage }) {
  const user = message.role === "user";
  return (
    <article className={cx("chat-message", user ? "user" : "assistant")}>
      {!user && (
        <span className="chat-avatar" aria-hidden>
          <img src="/igad-seal-white.png" alt="" width={22} height={22} />
        </span>
      )}
      <div className="chat-bubble">
        <div className="chat-who">{user ? "You" : "Copilot"}</div>
        <div className="chat-text">{message.text}</div>
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
            Standard answer from the forecast data; the assistant could not
            respond just now.
          </p>
        )}
        {!user && <AnswerBasis message={message} />}
        {!!message.sources?.length && <Sources sources={message.sources} />}
      </div>
    </article>
  );
}

export default function Copilot() {
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
  const [historyOpen, setHistoryOpen] = useState(false);
  const stream = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const stickToBottom = useRef(true);
  const latest = useApi<ForecastDetail>("/forecasts/latest");

  const adopt = (data: ChatSession) => {
    setSession(data.id);
    setMessages(data.messages ?? []);
    setContext(data.context ?? null);
    setCountry(data.context?.country ?? REGION);
    setVariant(data.context?.variant ?? "");
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

  async function send(text: string) {
    const message = text.trim();
    if (!message || pending || restoring || restoreFailed) return;
    setPending(true);
    setError("");
    setInput("");
    stickToBottom.current = true;
    setAwayFromBottom(false);
    setMessages((old) => [...old, { role: "user", text: message }]);
    try {
      const answer = await mutate<ChatAnswer>("/chat", {
        message,
        session_id: session,
        context_mode: "operational",
        country,
        variant: variant || null,
        reset_context: resetContext,
      });
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
    } catch (e) {
      setMessages((old) => old.slice(0, -1));
      setInput((draft) => draft || message);
      setError((e as Error).message);
    } finally {
      setPending(false);
      composer.current?.focus();
    }
  }

  const forecast = latest.data;
  const pinned = context?.forecast_id && !resetContext ? context : null;
  const layers = forecast ? layersOf(forecast) : [];
  const countries = forecast?.countries.map((row) => row.country) ?? [];
  if (country !== REGION && !countries.includes(country))
    countries.push(country);
  const locked = pending || restoring;
  const span =
    pinned?.valid_start && pinned.valid_end
      ? [pinned.valid_start, pinned.valid_end]
      : forecast
        ? [forecast.valid_start, forecast.valid_end]
        : null;

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
        <div className={cx("copilot", historyOpen && "history-open")}>
          <aside className="copilot-history" aria-label="Conversations">
            <div className="history-head">
              <h2>Conversations</h2>
              <button
                type="button"
                className="history-new"
                aria-label="New conversation"
                disabled={locked}
                onClick={startNew}
              >
                <SquarePen size={16} aria-hidden /> New
              </button>
              <button
                type="button"
                className="history-close"
                aria-label="Close conversations"
                onClick={() => setHistoryOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
            {!sessions.length ? (
              <p className="history-empty">Your conversations are kept here.</p>
            ) : (
              <nav className="history-list" aria-label="Saved conversations">
                {sessions.slice(0, 20).map((item) => (
                  <button
                    key={item.id}
                    type="button"
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
                ))}
              </nav>
            )}
          </aside>
          <section className="chat-card" aria-label="Conversation">
            <header className="chat-context">
              <button
                type="button"
                className="context-icon history-toggle"
                aria-label="Show conversations"
                onClick={() => setHistoryOpen(true)}
              >
                <History size={18} />
              </button>
              <div className="context-forecast">
                <span>Forecast</span>
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
              </div>
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
              <Link href="/bulletin" className="context-link">
                <FileText size={16} aria-hidden /> Bulletin
              </Link>
              <button
                type="button"
                className="context-icon context-new"
                aria-label="New conversation"
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
              {restoring ? (
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
                  <Message key={index} message={message} />
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
            <form
              className="chat-compose"
              onSubmit={(e) => {
                e.preventDefault();
                send(input);
              }}
            >
              <label className="sr-only" htmlFor="copilot-question">
                Ask Forecaster Copilot
              </label>
              <textarea
                ref={composer}
                id="copilot-question"
                rows={1}
                maxLength={2000}
                disabled={restoring || restoreFailed}
                placeholder="Ask about the forecast"
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
                  pending || restoring || restoreFailed || !input.trim()
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
    </div>
  );
}
