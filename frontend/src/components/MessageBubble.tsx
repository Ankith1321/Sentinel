"use client";

import { Fragment } from "react";
import type { ChatMessage, Source } from "@/lib/api";

const CITATION_SPLIT = /(\[S\d+\])/;
const CITATION_MARKER = /^\[S\d+\]$/;

function AnswerText({ text }: { text: string }) {
  return (
    <p className="whitespace-pre-wrap text-sm leading-7 text-zinc-200">
      {text.split(CITATION_SPLIT).map((part, i) =>
        CITATION_MARKER.test(part) ? (
          <span key={i} className="mx-0.5 rounded-md border border-zinc-700 bg-zinc-950 px-1.5 py-0.5 font-mono text-xs text-zinc-300">
            {part.slice(1, -1)}
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </p>
  );
}

function SourceCard({ source }: { source: Source }) {
  const score = source.score ?? source.distance;
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-medium text-zinc-100">
          {source.id}: {source.title}
        </span>
        <span className="text-xs text-zinc-500">
          {source.language}
          {score !== null && score !== undefined ? ` · ${source.score !== null ? "score" : "distance"} ${score.toFixed(3)}` : ""}
        </span>
      </div>
      <div className="mt-1 break-all font-mono text-xs text-zinc-400">{source.path}</div>
      {source.preview && (
        <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap text-xs leading-6 text-zinc-300">{source.preview}</pre>
      )}
    </div>
  );
}

type Props = {
  message: ChatMessage;
  onRate: (message: ChatMessage, rating: -1 | 1) => void;
};

export function MessageBubble({ message, onRate }: Props) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl border border-zinc-800 bg-zinc-800 px-4 py-3 text-sm text-zinc-100">
          {message.content}
        </div>
      </div>
    );
  }

  if (message.failed) {
    return (
      <div role="alert" className="rounded-2xl border border-red-900 bg-red-950/40 p-4 text-sm text-red-300">
        {message.content}
      </div>
    );
  }

  const waiting = message.streaming && message.content === "";

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
      {waiting ? (
        <p className="text-sm text-zinc-400">Searching Superset and drafting a grounded answer…</p>
      ) : (
        <AnswerText text={message.content} />
      )}
      {message.streaming && !waiting && <span className="mt-1 inline-block h-4 w-1.5 animate-pulse bg-zinc-500" />}

      {message.sources && message.sources.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-xs font-medium text-zinc-400 hover:text-zinc-200">
            Sources ({message.sources.length})
          </summary>
          <div className="mt-3 space-y-3">
            {message.sources.map((source) => (
              <SourceCard key={source.id} source={source} />
            ))}
          </div>
        </details>
      )}

      {!message.streaming && (
        <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-zinc-500">
          <button
            type="button"
            aria-label="Helpful answer"
            aria-pressed={message.rating === 1}
            disabled={message.messageId === undefined}
            onClick={() => onRate(message, 1)}
            className="cursor-pointer rounded-lg border border-zinc-800 px-2.5 py-1 hover:border-zinc-600 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40 aria-pressed:border-zinc-400 aria-pressed:text-zinc-100"
          >
            Helpful
          </button>
          <button
            type="button"
            aria-label="Not helpful answer"
            aria-pressed={message.rating === -1}
            disabled={message.messageId === undefined}
            onClick={() => onRate(message, -1)}
            className="cursor-pointer rounded-lg border border-zinc-800 px-2.5 py-1 hover:border-zinc-600 hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40 aria-pressed:border-zinc-400 aria-pressed:text-zinc-100"
          >
            Not helpful
          </button>
          {message.model && (
            <span>
              {message.model}
              {message.latencyMs !== undefined ? ` · ${(message.latencyMs / 1000).toFixed(1)}s` : ""}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
