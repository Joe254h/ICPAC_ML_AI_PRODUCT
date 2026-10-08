"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  Bot,
  Send,
  Plus,
  History,
  ArrowDown,
  LoaderCircle,
} from "lucide-react";
import { mutate, request } from "@/services/api";
import { useApi } from "@/services/hooks";
import type { ForecastDetail } from "@/types/operational";
import type {
  ChatAnswer,
  ChatContext,
  ChatMessage,
  ChatSession,
} from "@/types/workflows";
import Sources from "@/components/sources";

const suggestions = [
  "Explain the latest forecast for Kenya.",
  "Show the rainfall map for Somalia.",
  "What does MBC mean?",
  "Prepare the weekly bulletin in the supplied format.",
];
const STORAGE = "icpac-copilot-session";

export default function Copilot() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [session, setSession] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [context, setContext] = useState<ChatContext | null>(null);
  const [country, setCountry] = useState("GHA");
  const [variant, setVariant] = useState<"hybrid" | "mbc" | "raw">("hybrid");
  const [resetContext, setResetContext] = useState(false);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [restoreFailed, setRestoreFailed] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState("");
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const stream = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const stickToBottom = useRef(true);
  const latest = useApi<ForecastDetail>("/forecasts/latest");

  useEffect(() => {
    let mounted = true;
    request<ChatSession[]>("/chat/sessions")
      .then((data) => {
        if (mounted) setSessions(data);
      })
      .catch(() => {});
    const id = localStorage.getItem(STORAGE);
    if (!id) {
      setRestoring(false);
      return () => {
        mounted = false;
      };
    }
    request<ChatSession>("/chat/sessions/" + encodeURIComponent(id))
      .then((data) => {
        if (!mounted) return;
        setSession(data.id);
        setMessages(data.messages ?? []);
        setContext(data.context ?? null);
        setCountry(data.context?.country ?? "GHA");
        setVariant(data.context?.variant ?? "hybrid");
      })
      .catch((e) => {
        if (!mounted) return;
        if (e.status === 404) localStorage.removeItem(STORAGE);
        else {
          setRestoreFailed(true);
          setSession(id);
          setError(
            "Couldn't restore your conversation. Refresh to retry; it is still saved.",
          );
        }
      })
      .finally(() => {
        if (mounted) setRestoring(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (stickToBottom.current && stream.current) {
      stream.current.scrollTop = stream.current.scrollHeight;
    }
  }, [messages, pending, restoring]);

  async function openSession(id: string) {
    if (pending || restoring) return;
    setRestoring(true);
    setError("");
    try {
      const data = await request<ChatSession>(
        "/chat/sessions/" + encodeURIComponent(id),
      );
      stickToBottom.current = true;
      setAwayFromBottom(false);
      setSession(data.id);
      setRestoreFailed(false);
      setMessages(data.messages ?? []);
      setContext(data.context ?? null);
      setCountry(data.context?.country ?? "GHA");
      setVariant(data.context?.variant ?? "hybrid");
      setResetContext(false);
      setInput("");
      localStorage.setItem(STORAGE, data.id);
      setShowHistory(false);
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
    setCountry("GHA");
    setVariant("hybrid");
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
        variant,
        reset_context: resetContext,
      });
      setMessages((old) => [...old, { ...answer, role: "assistant" }]);
      setSession(answer.session_id);
      setContext(answer.context ?? null);
      setCountry(answer.context?.country ?? country);
      setVariant(answer.context?.variant ?? variant);
      setResetContext(false);
      localStorage.setItem(STORAGE, answer.session_id);
      const now = new Date().toISOString();
      setSessions((old) => [
        {
          id: answer.session_id,
          title:
            old.find((s) => s.id === answer.session_id)?.title ??
            message.slice(0, 80),
          created_at:
            old.find((s) => s.id === answer.session_id)?.created_at ?? now,
          updated_at: now,
          message_count: messages.length + 2,
          context: answer.context,
        },
        ...old.filter((s) => s.id !== answer.session_id),
      ]);
    } catch (e) {
      setMessages((old) => old.slice(0, -1));
      setInput((draft) => draft || message);
      setError((e as Error).message);
    } finally {
      setPending(false);
      composer.current?.focus();
    }
  }

  const active =
    context?.mode === "operational" && context.forecast_id && !resetContext
      ? context
      : latest.data;
  const countries = latest.data?.countries.map((row) => row.country) ?? [];
  if (country !== "GHA" && !countries.includes(country))
    countries.push(country);
  return (
    <section className="panel copilot-workspace">
      <div className="panel-head">
        <div>
          <h2>Forecaster Copilot</h2>
          <p>Continue the conversation about your forecast.</p>
        </div>
        <div className="action-row">
          <button
            className="button secondary"
            onClick={() => setShowHistory(!showHistory)}
            aria-expanded={showHistory}
          >
            <History size={14} /> Conversations
          </button>
          <button
            className="button secondary"
            disabled={pending || restoring}
            onClick={newConversation}
          >
            <Plus size={14} /> New conversation
          </button>
        </div>
      </div>
      {showHistory && (
        <nav className="conversation-history" aria-label="Saved conversations">
          {!sessions.length && <p>No saved conversations yet.</p>}
          {sessions.map((item) => (
            <button
              key={item.id}
              disabled={pending || restoring}
              aria-current={item.id === session ? "true" : undefined}
              onClick={() => openSession(item.id)}
            >
              <span>{item.title}</span>
              <small>{item.message_count} messages</small>
            </button>
          ))}
        </nav>
      )}
      <div className="chat-context">
        <div>
          <strong>
            {active?.forecast_id
              ? `Forecast ${active.forecast_id}`
              : latest.loading
                ? "Loading latest forecast…"
                : "No forecast package available"}
          </strong>
          <p>
            {active?.model_id && `${active.model_id} · ${active.model_status}`}
            {active?.synthetic && " · Synthetic test inputs"}
          </p>
          <p>
            Follow-up questions keep this forecast. Ask for “latest” to switch
            to the newest package.
          </p>
        </div>
        <button
          className="button secondary"
          disabled={pending || restoring}
          onClick={() => {
            setResetContext(true);
            latest.reload();
          }}
        >
          Use latest forecast
        </button>
      </div>
      <div className="chat-context-controls">
        <label>
          Country
          <select
            aria-label="Conversation country"
            value={country}
            disabled={pending || restoring}
            onChange={(e) => setCountry(e.target.value)}
          >
            <option value="GHA">Greater Horn of Africa</option>
            {countries.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Rainfall method
          <select
            aria-label="Conversation rainfall method"
            value={variant}
            disabled={pending || restoring}
            onChange={(e) => setVariant(e.target.value as typeof variant)}
          >
            <option value="hybrid">MBC + AI/ML</option>
            <option value="mbc">MBC</option>
            <option value="raw">Raw ECMWF</option>
          </select>
        </label>
        <Link href="/bulletin" className="small-link">
          Weekly bulletin
        </Link>
      </div>
      <div
        ref={stream}
        className="chat-stream"
        role="log"
        aria-label="Conversation messages"
        aria-live="polite"
        aria-busy={pending || restoring}
        onScroll={() => {
          const node = stream.current;
          if (!node) return;
          stickToBottom.current =
            node.scrollHeight - node.scrollTop - node.clientHeight < 80;
          setAwayFromBottom(!stickToBottom.current);
        }}
      >
        {restoring ? (
          <p role="status">Loading conversation…</p>
        ) : !messages.length ? (
          <div className="chat-welcome">
            <div className="copilot-orb">
              <Bot size={26} />
            </div>
            <h3>What would you like to explore?</h3>
            <p>
              Ask a question, then follow up with “And Somalia?” or “Tell me
              more.”
            </p>
            <div className="suggestions">
              {suggestions.map((text) => (
                <button
                  key={text}
                  disabled={pending || restoring || restoreFailed}
                  onClick={() => send(text)}
                >
                  {text}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message, index) => (
            <article key={index} className={"chat-message " + message.role}>
              <div className="message-label">
                {message.role === "user" ? "You" : "Copilot"}
              </div>
              <div className="narrative">{message.text}</div>
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
                    <Link key={link.url} href={link.url} className="small-link">
                      {link.label}
                    </Link>
                  ))}
                </div>
              )}
              {message.fallback && (
                <p className="subtle-alert">
                  The language model is unavailable. Showing the validated
                  forecast explanation.
                </p>
              )}
              {!!message.sources?.length && (
                <details className="chat-evidence">
                  <summary>Sources ({message.sources.length})</summary>
                  <Sources sources={message.sources} />
                </details>
              )}
              {!!message.tool_trace?.length && (
                <details className="tool-trace">
                  <summary>
                    Inspect tool evidence ·{" "}
                    {message.tool_trace.map((t) => t.tool).join(", ")}
                  </summary>
                  <pre>{JSON.stringify(message.tool_trace, null, 2)}</pre>
                </details>
              )}
              {message.provider && (
                <small className="chat-provider">{message.provider}</small>
              )}
            </article>
          ))
        )}
        {pending && (
          <div className="chat-message assistant chat-thinking" role="status">
            <LoaderCircle size={16} className="animate-spin" /> Preparing your
            answer…
          </div>
        )}
      </div>
      {awayFromBottom && (
        <button
          className="button secondary chat-jump"
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
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {restoreFailed && session && (
        <button
          className="button secondary"
          onClick={() => openSession(session)}
        >
          Retry loading conversation
        </button>
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
          placeholder="Ask a question or continue the conversation…"
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
          className="button primary"
          disabled={pending || restoring || restoreFailed || !input.trim()}
        >
          <Send size={16} /> Send
        </button>
      </form>
      <p className="chat-hint">
        Enter to send · Shift+Enter for a new line · Bulletins require
        forecaster review
      </p>
    </section>
  );
}
