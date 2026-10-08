"use client";
import { useEffect, useState } from "react";
import { Bot, Send, Plus, ShieldCheck } from "lucide-react";
import { mutate, request } from "@/services/api";
import type { Selection } from "@/types";
import type { ChatAnswer, ChatMessage } from "@/types/workflows";
import Sources from "@/components/sources";
const suggestions = [
  "Summarise this week's rainfall forecast.",
  "What is the forecast for Somalia?",
  "Has this forecast been verified?",
  "Which model produced this forecast?",
  "What is MBC?",
];
export default function Copilot({ selection }: { selection: Selection }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]),
    [session, setSession] = useState<string | null>(null),
    [input, setInput] = useState(""),
    [pending, setPending] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    const id = localStorage.getItem("icpac-copilot-session");
    if (id) {
      request<{ messages: ChatMessage[] }>("/chat/sessions/" + id)
        .then((data) => {
          setSession(id);
          setMessages(data.messages);
        })
        .catch(() => localStorage.removeItem("icpac-copilot-session"));
    }
  }, []);
  async function send(text: string) {
    if (!text.trim() || pending) return;
    setPending(true);
    setError("");
    setInput("");
    setMessages((old) => [...old, { role: "user", text }]);
    try {
      // Answers come from the latest forecast of the model in use.
      const answer = await mutate<ChatAnswer>("/chat", {
        message: text,
        selection,
        scope: "operational",
        session_id: session,
      });
      setMessages((old) => [...old, { ...answer, role: "assistant" }]);
      setSession(answer.session_id);
      localStorage.setItem("icpac-copilot-session", answer.session_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="panel copilot-workspace">
      <div className="panel-head">
        <div>
          <h2>Forecaster Copilot</h2>
          <p>
            Grounded climate tools · approved local references · saved
            conversation
          </p>
        </div>
        <button
          className="button secondary"
          disabled={pending}
          onClick={() => {
            setMessages([]);
            setSession(null);
            localStorage.removeItem("icpac-copilot-session");
          }}
        >
          <Plus size={14} />
          New conversation
        </button>
      </div>
      <div className="grounding-bar">
        <ShieldCheck size={16} />
        <span>
          Answers use the latest forecast of the model in use. Values come from
          Python tools; the language model only chooses and orders approved
          sentences. Drafts require human review.
        </span>
      </div>
      <div className="chat-stream" aria-live="polite">
        {!messages.length ? (
          <div className="chat-welcome">
            <div className="copilot-orb">
              <Bot size={26} />
            </div>
            <h3>Explore the forecast evidence</h3>
            <p>
              Ask about this week&apos;s rainfall, a country, verification, the
              model or a term.
            </p>
            <div className="suggestions">
              {suggestions.map((text) => (
                <button key={text} onClick={() => send(text)}>
                  {text}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message, index) => (
            <article key={index} className={"chat-message " + message.role}>
              <div className="message-label">
                {message.role === "user" ? "Forecaster" : "Copilot"}
                {message.provider && (
                  <span className="badge green">{message.provider}</span>
                )}
              </div>
              <div className="narrative">{message.text}</div>
              {message.fallback && (
                <p className="subtle-alert">{message.fallback}</p>
              )}
              {message.sources && <Sources sources={message.sources} />}{" "}
              {!!message.tool_trace?.length && (
                <details className="tool-trace">
                  <summary>
                    Inspect tool evidence ·{" "}
                    {message.tool_trace.map((t) => t.tool).join(", ")}
                  </summary>
                  <pre>{JSON.stringify(message.tool_trace, null, 2)}</pre>
                </details>
              )}
            </article>
          ))
        )}
        {pending && (
          <div className="chat-message assistant">
            Calling validated climate tools…
          </div>
        )}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
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
          id="copilot-question"
          rows={2}
          maxLength={2000}
          placeholder="Ask about rainfall, verification, datasets or a draft…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
        <button className="button primary" disabled={pending || !input.trim()}>
          <Send size={16} />
          Send
        </button>
      </form>
    </section>
  );
}
