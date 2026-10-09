"use client";
/** Forecaster Copilot: questions about the latest forecast, answered from its own numbers. */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowDown,
  Bot,
  FileText,
  LoaderCircle,
  MessageSquarePlus,
  RefreshCw,
  Send,
} from "lucide-react";
import { Button, Notice, PageBanner } from "@/components/ui";
import { cx } from "@/components/ui";
import { LAYER_TEXT, layersOf } from "@/features/operational/shared";
import { day, validDays } from "@/lib/format";
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
  "What does MBC mean?",
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
            <span>{source.category.replaceAll("_", " ")}</span>
            <p>{source.excerpt}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}

function Message({ message }: { message: ChatMessage }) {
  const user = message.role === "user";
  return (
    <article className={cx("chat-message", user ? "user" : "assistant")}>
      {!user && (
        <span className="chat-avatar" aria-hidden>
          <Bot size={18} />
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
            The language model did not answer, so this is the checked forecast
            explanation.
          </p>
        )}
        {!!message.sources?.length && <Sources sources={message.sources} />}
        {!!message.tool_trace?.length && (
          <details className="chat-details">
            <summary>
              Forecast data used ·{" "}
              {message.tool_trace.map((t) => t.tool).join(", ")}
            </summary>
            <pre>{JSON.stringify(message.tool_trace, null, 2)}</pre>
          </details>
        )}
        {message.provider && (
          <small className="chat-provider">{message.provider}</small>
        )}
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

  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="Forecaster Copilot"
          crumbs={[{ label: "Copilot" }]}
          subtitle="Ask about the week's forecast in plain language. Answers are built from the forecast's own numbers, maps and verification, and every figure can be traced to the data used."
          facts={[
            "Self-hosted language model",
            "Answers cite the forecast",
            "Bulletins still need review",
          ]}
        />
        <div className="copilot">
          <aside className="copilot-side">
            <Button variant="amber" disabled={locked} onClick={newConversation}>
              <MessageSquarePlus size={18} /> New conversation
            </Button>
            <section className="side-block">
              <h3>Forecast in discussion</h3>
              {latest.loading && <p>Loading the latest forecast…</p>}
              {latest.status === 404 && (
                <p>
                  No forecast has been issued yet. Run the weekly cycle in{" "}
                  <Link href="/data/runs">Operations</Link>.
                </p>
              )}
              {forecast && (
                <>
                  <p className="side-strong">
                    {pinned?.valid_start && pinned.valid_end
                      ? validDays(pinned.valid_start, pinned.valid_end)
                      : validDays(forecast.valid_start, forecast.valid_end)}
                  </p>
                  <p>
                    ECMWF run of {day(forecast.initialization)} ·{" "}
                    {pinned?.model_id ?? forecast.model_id}
                  </p>
                  {pinned && pinned.forecast_id !== forecast.forecast_id && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={locked}
                      onClick={() => {
                        setResetContext(true);
                        latest.reload();
                      }}
                    >
                      <RefreshCw size={14} /> Switch to the latest forecast
                    </Button>
                  )}
                </>
              )}
              <label className="field">
                Area
                <select
                  aria-label="Conversation country"
                  value={country}
                  disabled={locked}
                  onChange={(e) => setCountry(e.target.value)}
                >
                  <option value={REGION}>Greater Horn of Africa</option>
                  {countries.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                Forecast layer
                <select
                  aria-label="Conversation rainfall method"
                  value={variant}
                  disabled={locked}
                  onChange={(e) => setVariant(e.target.value as Variant | "")}
                >
                  <option value="">Main forecast</option>
                  {layers.map((layer) => (
                    <option key={layer} value={layer}>
                      {LAYER_TEXT[layer].title}
                    </option>
                  ))}
                </select>
              </label>
              <Link href="/bulletin" className="link-amber">
                <FileText size={15} /> Weekly bulletin →
              </Link>
            </section>
            <section className="side-block">
              <h3>Conversations</h3>
              {!sessions.length && <p>No saved conversation yet.</p>}
              <nav
                className="conversation-list"
                aria-label="Saved conversations"
              >
                {sessions.slice(0, 12).map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    disabled={locked}
                    aria-current={item.id === session ? "true" : undefined}
                    onClick={() => openSession(item.id)}
                  >
                    <span>{item.title}</span>
                    <small>
                      {item.message_count} messages · {day(item.updated_at)}
                    </small>
                  </button>
                ))}
              </nav>
            </section>
          </aside>
          <section className="chat-card" aria-label="Conversation">
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
                  <span className="chat-orb" aria-hidden>
                    <Bot size={30} />
                  </span>
                  <h2>How can I help with this week&apos;s forecast?</h2>
                  <p>
                    Ask a question, then follow up with “And Somalia?” or “Tell
                    me more.” The conversation keeps the same forecast until you
                    switch.
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
                  <LoaderCircle size={16} className="spin" /> Preparing the
                  answer…
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
                rows={2}
                maxLength={2000}
                disabled={restoring || restoreFailed}
                placeholder="Ask about the forecast…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
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
                className="btn btn-green"
                disabled={
                  pending || restoring || restoreFailed || !input.trim()
                }
              >
                <Send size={16} /> Send
              </button>
            </form>
            <p className="chat-hint">
              Enter to send · Shift+Enter for a new line · Answers support, and
              do not replace, the forecaster&apos;s judgement
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
