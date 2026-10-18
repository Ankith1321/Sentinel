"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createSession,
  getSession,
  listSessions,
  sendFeedback,
  streamQuery,
  type ChatMessage,
  type SessionSummary,
} from "@/lib/api";
import { MessageBubble } from "./MessageBubble";

const SESSION_KEY = "sentinel.sessionId";
const MIN_QUESTION_LENGTH = 3;

function remember(id: string | null) {
  try {
    if (id) window.localStorage.setItem(SESSION_KEY, id);
    else window.localStorage.removeItem(SESSION_KEY);
  } catch {
    return;
  }
}

function recall(): string | null {
  try {
    return window.localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

async function loadMessages(id: string): Promise<ChatMessage[]> {
  const session = await getSession(id);
  return session.messages.map((m) => ({
    key: `m${m.id}`,
    role: m.role,
    content: m.content,
    sources: m.sources,
    messageId: m.role === "assistant" ? m.id : undefined,
  }));
}

export function Chat() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [topK, setTopK] = useState(5);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await listSessions());
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not load sessions");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function restore() {
      const saved = recall();
      if (saved) {
        try {
          const restored = await loadMessages(saved);
          if (!cancelled) {
            setSessionId(saved);
            setMessages(restored);
          }
        } catch {
          remember(null);
        }
      }
      if (!cancelled) await refreshSessions();
    }

    restore();
    return () => {
      cancelled = true;
    };
  }, [refreshSessions]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function openSession(id: string) {
    if (busy) return;
    setNotice("");
    try {
      setMessages(await loadMessages(id));
      setSessionId(id);
      remember(id);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not open session");
    }
  }

  function newChat() {
    if (busy) return;
    setSessionId(null);
    setMessages([]);
    setNotice("");
    remember(null);
  }

  async function send() {
    const question = input.trim();
    if (question.length < MIN_QUESTION_LENGTH || busy) return;

    setBusy(true);
    setInput("");
    setNotice("");

    const draftKey = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { key: crypto.randomUUID(), role: "user", content: question },
      { key: draftKey, role: "assistant", content: "", streaming: true },
    ]);
    const patch = (changes: Partial<ChatMessage>) =>
      setMessages((prev) => prev.map((m) => (m.key === draftKey ? { ...m, ...changes } : m)));

    const controller = new AbortController();
    abortRef.current = controller;
    let text = "";

    try {
      let id = sessionId;
      if (!id) {
        id = (await createSession()).session_id;
        setSessionId(id);
        remember(id);
      }

      for await (const event of streamQuery({ question, top_k: topK, session_id: id }, controller.signal)) {
        if (event.event === "sources") {
          patch({ sources: event.data.sources });
        } else if (event.event === "token") {
          text += event.data;
          patch({ content: text });
        } else if (event.event === "error") {
          throw new Error(event.data.detail);
        } else {
          patch({
            content: event.data.answer,
            sources: event.data.sources,
            messageId: event.data.message_id,
            model: event.data.model,
            latencyMs: event.data.retrieval_ms + event.data.generation_ms,
            streaming: false,
          });
        }
      }
      patch({ streaming: false });
      await refreshSessions();
    } catch (err) {
      if (controller.signal.aborted) {
        patch({ streaming: false, content: text || "Stopped before an answer was produced." });
      } else {
        patch({
          streaming: false,
          failed: true,
          content: err instanceof Error ? err.message : "Something went wrong",
        });
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  async function rate(message: ChatMessage, rating: -1 | 1) {
    if (message.messageId === undefined) return;
    setMessages((prev) => prev.map((m) => (m.key === message.key ? { ...m, rating } : m)));
    try {
      await sendFeedback(message.messageId, rating);
    } catch (err) {
      setMessages((prev) => prev.map((m) => (m.key === message.key ? { ...m, rating: undefined } : m)));
      setNotice(err instanceof Error ? err.message : "Could not save feedback");
    }
  }

  return (
    <div className="grid gap-6 md:grid-cols-[250px_1fr]">
      <aside className="space-y-3">
        <button
          type="button"
          onClick={newChat}
          disabled={busy}
          className="w-full cursor-pointer rounded-xl bg-white px-4 py-2 text-sm font-medium text-zinc-950 disabled:cursor-not-allowed disabled:opacity-50"
        >
          New chat
        </button>
        <nav aria-label="Past sessions" className="max-h-72 space-y-2 overflow-auto md:max-h-[60vh]">
          {sessions.length === 0 && <p className="text-xs text-zinc-500">No conversations yet.</p>}
          {sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => openSession(s.id)}
              aria-current={s.id === sessionId}
              className="w-full cursor-pointer truncate rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2 text-left text-xs text-zinc-300 hover:border-zinc-600 aria-[current=true]:border-zinc-400 aria-[current=true]:text-zinc-100"
            >
              {s.first_question ?? "New conversation"}
            </button>
          ))}
        </nav>
      </aside>

      <section className="flex min-w-0 flex-col gap-4">
        {messages.length === 0 && (
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-6">
            <h2 className="text-xl font-semibold">Ask about the Superset codebase</h2>
            <p className="mt-2 text-sm text-zinc-400">
              Answers come only from retrieved source files and cite them as [S1], [S2]. Try:
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {[
                "How does the cache manager configure caches?",
                "Where is get_since_until implemented?",
                "How do I run Superset with Docker Compose?",
              ].map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setInput(example)}
                  className="cursor-pointer rounded-xl border border-zinc-700 px-3 py-1.5 text-left text-xs text-zinc-300 hover:border-zinc-500"
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="space-y-4">
          {messages.map((m) => (
            <MessageBubble key={m.key} message={m} onRate={rate} />
          ))}
        </div>

        {notice && (
          <div role="alert" className="rounded-2xl border border-red-900 bg-red-950/40 p-3 text-sm text-red-300">
            {notice}
          </div>
        )}

        <div ref={bottomRef} />

        <div className="sticky bottom-0 rounded-2xl border border-zinc-800 bg-zinc-900 p-4">
          <label htmlFor="question" className="sr-only">
            Your question
          </label>
          <textarea
            id="question"
            className="min-h-20 w-full resize-y rounded-xl border border-zinc-700 bg-zinc-950 p-3 text-sm text-zinc-100 outline-none focus:border-zinc-500"
            placeholder="Ask about Apache Superset…"
            value={input}
            maxLength={2000}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <label htmlFor="top-k" className="flex items-center gap-3 text-xs text-zinc-400">
              Sources per answer
              <input
                id="top-k"
                type="range"
                min={1}
                max={15}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className="accent-white"
              />
              <span className="w-4 text-zinc-200">{topK}</span>
            </label>
            {busy ? (
              <button
                type="button"
                onClick={() => abortRef.current?.abort()}
                className="cursor-pointer rounded-xl border border-zinc-600 px-5 py-2 text-sm font-medium text-zinc-100"
              >
                Stop
              </button>
            ) : (
              <button
                type="button"
                onClick={send}
                disabled={input.trim().length < MIN_QUESTION_LENGTH}
                className="cursor-pointer rounded-xl bg-white px-5 py-2 text-sm font-medium text-zinc-950 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Ask Sentinel
              </button>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
